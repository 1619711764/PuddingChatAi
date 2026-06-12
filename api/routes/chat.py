# Chat 路由 v2 — 多用户 + SSE 流式 + 记忆注入
# 使用 FastAPI Depends 进行 JWT 认证

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from core.llm_client import LLMClient
from core.database import Database
from core.memory import MemoryEngine
from core.persona import PersonaEngine, _default_prompt
from api.middleware.auth import get_current_user

router = APIRouter(prefix="/api", tags=["chat"])

# 模块级变量
llm: LLMClient | None = None
db: Database | None = None
memory_engine: MemoryEngine | None = None
persona_engine: PersonaEngine | None = None


def init_chat_routes(llm_client: LLMClient, database: Database,
                     pers_engine: PersonaEngine = None):
    global llm, db, memory_engine, persona_engine
    llm = llm_client
    db = database
    persona_engine = pers_engine
    if llm and db:
        memory_engine = MemoryEngine(llm, db)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: str | None = None
    stream: bool = True
    persona_id: str | None = None


class RegenerateRequest(BaseModel):
    conversation_id: str


class UpdateTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


SYSTEM_PROMPT = _default_prompt()


# ── 路由 ──

@router.post("/chat")
async def chat(req: ChatRequest, request: Request, user_id: str = Depends(get_current_user)):
    if not llm or not db:
        raise HTTPException(500, "Service not initialized")

    # 获取或创建对话
    cid = req.conversation_id
    is_new_conv = False
    if not cid:
        conv = db.create_conversation(user_id)
        cid = conv["id"]
        is_new_conv = True
    else:
        conv = db.get_conversation(cid)
        if not conv or conv.get("user_id") != user_id:
            raise HTTPException(403, "Access denied")

    # 自动标题
    if is_new_conv:
        title = req.message[:30].replace("\n", " ")
        db.update_title(cid, title)

    # 保存用户消息
    db.add_message(cid, "user", req.message)

    # 收集风格样本（用于蒸馏 AI 人格）
    if persona_engine and user_id:
        persona_engine.collect_style(user_id, req.message, req.persona_id)

    # 获取对话历史
    history = db.get_messages(cid, limit=30)

    # 构建 messages — 使用人格引擎
    if persona_engine:
        system_content = persona_engine.build_system_prompt(
            req.persona_id, user_id, memory_engine)
        if req.persona_id:
            persona_engine.record_usage(req.persona_id)
    else:
        system_content = SYSTEM_PROMPT
        if memory_engine:
            memory_ctx = memory_engine.build_context(user_id)
            if memory_ctx:
                system_content += memory_ctx

    messages = [{"role": "system", "content": system_content}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    if req.stream:
        return StreamingResponse(
            _stream_reply(cid, user_id, messages),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Conversation-Id": cid,
            },
        )
    else:
        reply = llm.chat(messages, stream=False)
        db.add_message(cid, "assistant", reply)
        return {"reply": reply, "conversation_id": cid}


async def _stream_reply(conv_id: str, user_id: str, messages: list[dict]):
    """SSE streaming with memory extraction"""
    full_reply = ""
    try:
        yield f"event: meta\ndata: {conv_id}\n\n"
        for token in llm.chat(messages, stream=True):
            full_reply += token
            yield f"data: {token}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
    except Exception as e:
        yield f"event: error\ndata: {str(e)}\n\n"
    finally:
        if full_reply and db:
            try:
                db.add_message(conv_id, "assistant", full_reply)
            except Exception:
                pass
        # Extract memories in background
        if full_reply and memory_engine:
            try:
                if db.get_message_count(conv_id) >= 4:
                    memory_engine.extract_and_save(user_id, conv_id)
            except Exception:
                pass
        # 触发风格蒸馏（每 15 条一次）
        if full_reply and persona_engine and user_id:
            try:
                count = db.count_style_samples(user_id)
                if count >= 15 and count % 15 < 3:
                    # 找到该用户关联的人格 ID
                    personas = db.get_personas(include_system=True)
                    for p in personas:
                        if not p["is_system"]:
                            persona_engine.distill(user_id, p["id"], llm)
            except Exception:
                pass


# ── Regenerate ──

@router.post("/chat/regenerate")
async def regenerate(req: RegenerateRequest, request: Request, user_id: str = Depends(get_current_user)):
    if not llm or not db:
        raise HTTPException(500, "Service not initialized")

    conv = db.get_conversation(req.conversation_id)
    if not conv or conv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")

    messages = db.get_messages(req.conversation_id, limit=30)
    if messages and messages[-1]["role"] == "assistant":
        messages.pop()

    user_messages = [m for m in messages if m["role"] == "user"]
    if not user_messages:
        raise HTTPException(400, "No message to regenerate")

    if persona_engine:
        system_content = persona_engine.build_system_prompt(None, user_id, memory_engine)
    else:
        system_content = SYSTEM_PROMPT
        if memory_engine:
            memory_ctx = memory_engine.build_context(user_id)
            if memory_ctx:
                system_content += memory_ctx

    llm_messages = [{"role": "system", "content": system_content}]
    for m in messages:
        llm_messages.append({"role": m["role"], "content": m["content"]})

    return StreamingResponse(
        _stream_reply(req.conversation_id, user_id, llm_messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Conversation CRUD ──

@router.get("/conversations")
async def list_conversations(request: Request, user_id: str = Depends(get_current_user)):
    if not db:
        raise HTTPException(500, "Service not initialized")
    return db.list_conversations(user_id)


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, request: Request, user_id: str = Depends(get_current_user)):
    if not db:
        raise HTTPException(500, "Service not initialized")
    conv = db.get_conversation(conv_id)
    if not conv or conv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    msgs = db.get_messages(conv_id)
    return {"id": conv_id, "title": conv.get("title", ""), "messages": msgs}


@router.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: str, req: UpdateTitleRequest, user_id: str = Depends(get_current_user)):
    if not db:
        raise HTTPException(500, "Service not initialized")
    conv = db.get_conversation(conv_id)
    if not conv or conv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")

    title = req.title.strip()
    db.update_title(conv_id, title)
    return {"ok": True, "title": title}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, request: Request, user_id: str = Depends(get_current_user)):
    if not db:
        raise HTTPException(500, "Service not initialized")
    conv = db.get_conversation(conv_id)
    if not conv or conv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    db.delete_conversation(conv_id)
    return {"ok": True}
