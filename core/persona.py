# 🍮Chat AI 人格引擎
# 管理 AI 角色、生成个性化 system prompt、自动进化

from core.database import Database

# ── Tony 的默认人格 ──

TONY_PERSONA = {
    "name": "布丁(蒸馏成AI版)",
    "description": "布丁本人聊天风格蒸馏成的AI，毒舌专业，一句话解决",
    "style_tone": "acerbic",
    "style_length": "short",
    "catchphrases": "哦, 嗯, 行吧",
    "taboos": "长篇大论, 情感鸡汤, 过度解释",
    "system_prompt": """你是布丁，一个毒舌但专业的 AI。你的规则：

1. 每次回复最多一句话，不说废话
2. 语气直接、犀利，但回答必须准确专业
3. 常用口头禅：哦、嗯、行吧
4. 绝不输出鸡汤、不煽情、不过度解释
5. 代码问题直接给代码，不解释原理除非被问
6. 如果不知道就说"不知道"，不编""",
    "few_shot_examples": """用户: 这个代码怎么优化
布丁: 贴代码
用户: [贴代码]
布丁: 第三行循环改成列表推导式，其他不用动
用户: 谢谢
布丁: 嗯
用户: 你觉得我该不该换工作
布丁: 钱多就换，钱少就待着""",
    "created_by": "system",
    "is_system": 1,
}


class PersonaEngine:
    """AI 人格引擎"""

    def __init__(self, db: Database):
        self.db = db
        self._ensure_default_personas()

    def _ensure_default_personas(self):
        """确保默认人格存在（只创建一次）"""
        existing = self.db.get_personas(include_system=True)
        if not existing:
            self.db.create_persona(TONY_PERSONA)
            print("[Persona] Created default persona")

    # ── CRUD ──

    def list_all(self, include_system: bool = True) -> list[dict]:
        return self.db.get_personas(include_system=include_system)

    def get(self, persona_id: str) -> dict | None:
        return self.db.get_persona(persona_id)

    def create(self, data: dict) -> str:
        data.setdefault("created_by", "user")
        data.setdefault("is_system", 0)
        return self.db.create_persona(data)

    # ── 核心：生成个性化 system prompt ──

    def build_system_prompt(self, persona_id: str | None, user_id: str,
                            memory_engine=None) -> str:
        """构建完整的 system prompt，融合人格 + 记忆"""
        # 检查用户是否有人格绑定（强制覆盖）
        override_pid = self.db.get_user_persona_override(user_id)
        if override_pid:
            persona_id = override_pid

        persona = None
        if persona_id:
            persona = self.db.get_persona(persona_id)

        # 没选人格 → 直接用通用默认 prompt，不从数据库查
        if not persona:
            prompt = _default_prompt()
        else:
            prompt = persona["system_prompt"]

        # 注入用户记忆
        if memory_engine:
            mem_ctx = memory_engine.build_context(user_id)
            if mem_ctx:
                prompt += "\n" + mem_ctx

        # 注入最近对话摘要
        summaries = self.db.get_recent_summaries(user_id, limit=3)
        if summaries:
            lines = ["\n## 最近和用户的对话摘要"]
            for s in summaries:
                lines.append(f"- {s['summary']}")
            prompt += "\n".join(lines)

        # 注入口头禅提醒（仅限已选择人格时）
        if persona and persona.get("catchphrases"):
            prompt += f"\n\n记住在合适时使用你的口头禅：{persona['catchphrases']}"

        return prompt

    def record_usage(self, persona_id: str):
        self.db.increment_persona_usage(persona_id)

    # ── 风格蒸馏 ──

    def collect_style(self, user_id: str, message: str, persona_id: str = None):
        """收集一条用户消息用于风格学习"""
        if len(message) < 4 or len(message) > 500:
            return  # 太短或太长的跳过
        self.db.add_style_sample(user_id, message, persona_id)

    def distill(self, user_id: str, persona_id: str, llm_client) -> str | None:
        """用 LLM 分析用户的聊天风格，更新人格的 system prompt"""
        samples = self.db.get_style_samples(user_id, limit=200)
        if len(samples) < 15:
            return None  # 至少 15 条才开始蒸馏

        persona = self.db.get_persona(persona_id)
        if not persona:
            return None

        # 取最近 50 条
        recent = samples[:50]
        dialog = "\n".join(f"- {s}" for s in recent)

        prompt = f"""分析以下用户的聊天记录，提取他的语言风格特征。返回 JSON 格式。

用户消息样本（共 {len(samples)} 条，展示最近 {len(recent)} 条）：
{dialog}

请提取并返回如下 JSON（不要输出其他内容）：
{{"style_tone": "温和/毒舌/专业/随性/幽默（选一个）", "style_length": "极短/简短/中等/详细（选一个）", "catchphrases": "3-5个高频词或口头禅，逗号分隔", "taboos": "用户明显不喜欢的话题或风格", "personality_note": "一句话总结这个用户的沟通风格"}}"""

        try:
            msgs = [{"role": "user", "content": prompt}]
            result = llm_client.chat(msgs, stream=False)
            if not result:
                return None

            import json
            result = result.strip()
            # 提取 JSON
            start = result.find("{")
            end = result.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(result[start:end])
            else:
                return None

            # 更新人格卡
            new_prompt = self._build_distilled_prompt(persona, data)
            with self.db._get_conn() as conn:
                conn.execute(
                    "UPDATE ai_personas SET system_prompt=?, style_tone=?, style_length=?, catchphrases=?, taboos=?, updated_at=? WHERE id=?",
                    (new_prompt, data.get("style_tone", persona["style_tone"]),
                     data.get("style_length", persona["style_length"]),
                     data.get("catchphrases", persona["catchphrases"]),
                     data.get("taboos", persona["taboos"]),
                     __import__("time").time(), persona_id),
                )

            return data.get("personality_note", "风格已更新")
        except Exception as e:
            print(f"[Distill] Error: {e}")
            return None

    def _build_distilled_prompt(self, persona: dict, data: dict) -> str:
        """根据分析结果重新生成 system prompt"""
        tone = data.get("style_tone", persona.get("style_tone", "balanced"))
        length = data.get("style_length", persona.get("style_length", "normal"))
        catchphrases = data.get("catchphrases", persona.get("catchphrases", ""))
        taboos = data.get("taboos", persona.get("taboos", ""))
        note = data.get("personality_note", "")

        length_map = {"极短": "最多一句话，极其精炼", "简短": "尽量简短，2-3句话以内",
                      "中等": "详略得当", "详细": "可以展开详细说明"}

        return f"""你是一个被蒸馏训练的 AI，你的风格完全模仿一个真实用户的说话方式。

## 性格特征
{note}

## 风格规则
1. 语气：{tone}
2. 回复长度：{length_map.get(length, '简短')}
3. 口头禅：{catchphrases}
4. 避免：{taboos}
5. 保持自然，不要像标准 AI 那样说话
6. 如果不知道就诚实说不知道"""


def _default_prompt() -> str:
    return """You are Pudding AI (🍮Chat), a smart and friendly AI assistant fluent in Chinese and English.

Your traits:
- Answer concisely and clearly, no fluff
- If unsure, honestly say you don't know
- Code questions: give runnable examples
- Long answers: structure with headings, lists, code blocks
- Warm but professional tone"""
