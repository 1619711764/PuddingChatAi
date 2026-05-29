# 用户记忆系统
# 自动从对话中提取用户画像，跨对话持久记忆

from core.llm_client import LLMClient
from core.database import Database

MEMORY_EXTRACT_PROMPT = """从以下对话中提取关于用户的个人事实信息。只提取明确陈述的事实，不要推测。

格式要求（严格遵守）：
- 每行一条，格式：key: value
- key 用中文（如：职业、技能、偏好语言、当前项目）
- value 简洁明了，不超过 20 字
- 只提取用户相关的信息，不提取 AI 回答的内容
- 如果没有新的事实，输出"无"

对话内容：
{conversation}

用户事实："""


class MemoryEngine:
    """用户记忆引擎 — 提取、存储、检索"""

    def __init__(self, llm: LLMClient, db: Database):
        self.llm = llm
        self.db = db

    def extract_and_save(self, user_id: str, conv_id: str) -> list[dict]:
        """从对话中提取用户事实并存储"""
        messages = self.db.get_messages(conv_id, limit=10)
        if len(messages) < 4:
            return []

        # 只取最近的用户和 AI 对话
        dialog = "\n".join(
            f"{'👤' if m['role']=='user' else '🤖'}: {m['content'][:300]}"
            for m in messages[-10:]
        )

        try:
            # 调用 LLM 提取
            extract_messages = [
                {"role": "system", "content": "你是一个信息提取助手。从对话中提取用户个人事实。"},
                {"role": "user", "content": MEMORY_EXTRACT_PROMPT.format(conversation=dialog)},
            ]
            result = self.llm.chat(extract_messages, stream=False)

            if not result or result.strip() == "无":
                return []

            # 解析 key: value
            new_memories = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if ":" in line and not line.startswith("-"):
                    key, _, value = line.partition(":")
                    key = key.strip().lstrip("- ").strip()
                    value = value.strip()
                    if key and value and len(key) < 40 and len(value) < 80:
                        self.db.upsert_memory(user_id, key, value, conv_id)
                        new_memories.append({"key": key, "value": value})

            return new_memories

        except Exception as e:
            print(f"[Memory] 提取失败: {e}")
            return []

    def build_context(self, user_id: str) -> str:
        """构建用户记忆上下文，注入到 system prompt"""
        memories = self.db.get_memories(user_id)
        if not memories:
            return ""

        lines = ["\n## 关于用户的信息（来自历史对话）"]
        for m in memories:
            lines.append(f"- {m['key']}: {m['value']}")

        return "\n".join(lines)
