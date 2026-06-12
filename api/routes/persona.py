# 🍮Chat Persona API — AI 人格管理

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from core.database import Database
from core.persona import PersonaEngine
from api.middleware.auth import get_current_user

router = APIRouter(prefix="/api/personas", tags=["personas"])

db: Database | None = None
persona_engine: PersonaEngine | None = None


def init_persona_routes(database: Database, engine: PersonaEngine):
    global db, persona_engine
    db = database
    persona_engine = engine


class CreatePersonaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = ""
    style_tone: str = "balanced"
    style_length: str = "normal"
    catchphrases: str = ""
    taboos: str = ""
    system_prompt: str = Field(..., min_length=1)


# ── 列表 ──

@router.get("")
async def list_personas(request: Request, user_id: str = Depends(get_current_user)):
    if not persona_engine or not db:
        raise HTTPException(500, "Service not initialized")
    all_personas = persona_engine.list_all(include_system=True)
    # 过滤私有人格：只显示无绑定 或 绑定到当前用户的
    visible = []
    for p in all_personas:
        bound_user = db.get_persona_bound_user(p["id"])
        if bound_user is None or bound_user == user_id:
            visible.append(p)
    return visible


# ── 详情 ──

@router.get("/{persona_id}")
async def get_persona(persona_id: str, request: Request,
                      user_id: str = Depends(get_current_user)):
    if not persona_engine:
        raise HTTPException(500, "Service not initialized")
    p = persona_engine.get(persona_id)
    if not p:
        raise HTTPException(404, "人格不存在")
    return p


# ── 创建 ──

@router.post("")
async def create_persona(req: CreatePersonaRequest, request: Request,
                         user_id: str = Depends(get_current_user)):
    if not persona_engine:
        raise HTTPException(500, "Service not initialized")

    data = req.model_dump()
    data["created_by"] = user_id
    pid = persona_engine.create(data)
    return {"ok": True, "persona_id": pid}


# ── 手动蒸馏 ──

@router.post("/{persona_id}/distill")
async def distill_persona(persona_id: str, request: Request,
                          user_id: str = Depends(get_current_user)):
    """手动触发风格蒸馏，用当前用户的聊天记录更新人格"""
    if not persona_engine:
        raise HTTPException(500, "Service not initialized")
    if not db:
        raise HTTPException(500, "数据库未初始化")

    # 需要 LLM 客户端
    from core.llm_client import LLMClient
    import os
    from core.config import LLMConfig
    llm_cfg = LLMConfig()
    llm = LLMClient(llm_cfg)

    count = db.count_style_samples(user_id)
    if count < 15:
        raise HTTPException(400, f"至少需要 15 条消息才能蒸馏，当前 {count} 条。请多聊几句。")

    result = persona_engine.distill(user_id, persona_id, llm)
    if result:
        return {"ok": True, "message": result, "samples_used": count}
    else:
        raise HTTPException(500, "蒸馏失败，请稍后重试")


# ── 样本统计 ──

@router.get("/{persona_id}/samples")
async def get_samples(persona_id: str, request: Request,
                      user_id: str = Depends(get_current_user)):
    if not db:
        raise HTTPException(500, "数据库未初始化")
    count = db.count_style_samples(user_id)
    return {"user_id": user_id, "samples": count, "min_required": 15,
            "ready": count >= 15}
