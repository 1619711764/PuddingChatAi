# 记忆 API — 用户画像管理

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from core.database import Database
from core.memory import MemoryEngine
from api.middleware.auth import get_current_user

router = APIRouter(prefix="/api/memories", tags=["memories"])

db: Database | None = None
memory_engine: MemoryEngine | None = None


def init_memory_routes(database: Database, mem_engine: MemoryEngine):
    global db, memory_engine
    db = database
    memory_engine = mem_engine


@router.get("")
async def list_memories(request: Request, user_id: str = Depends(get_current_user)):
    if not db:
        raise HTTPException(500, "Service not initialized")
    return db.get_memories(user_id)


@router.post("/extract")
async def extract_memories(request: Request, user_id: str = Depends(get_current_user)):
    """Manually trigger memory extraction"""
    if not db or not memory_engine:
        raise HTTPException(500, "Service not initialized")

    convs = db.list_conversations(user_id, limit=1)
    if not convs:
        return {"ok": True, "memories": [], "message": "No conversations to extract from"}

    conv_id = convs[0]["id"]
    memories = memory_engine.extract_and_save(user_id, conv_id)
    return {"ok": True, "memories": memories, "conv_id": conv_id}


class DeleteMemoryRequest(BaseModel):
    key: str


@router.delete("/{key}")
async def delete_memory(key: str, request: Request, user_id: str = Depends(get_current_user)):
    if not db:
        raise HTTPException(500, "Service not initialized")
    db.delete_memory(user_id, key)
    return {"ok": True}
