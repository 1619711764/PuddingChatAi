# 🍮Chat v2 — FastAPI 主应用（本地方案）
# SQLite 多用户 + JWT 认证 + DeepSeek API

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 加载 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from core.config import AppConfig
from core.llm_client import LLMClient
from core.database import Database
from core.memory import MemoryEngine
from api.routes.chat import router as chat_router, init_chat_routes
from api.routes.auth import router as auth_router, init_auth_routes
from api.routes.memory import router as memory_router, init_memory_routes
from api.routes.wechat_routes import wechat_verify, wechat_callback

cfg = AppConfig()

# ── 数据库（本地 SQLite） ──
os.makedirs(os.path.dirname(cfg.db_path), exist_ok=True)
db = Database(cfg)
print(f"[DB] SQLite ready: {cfg.db_path}")

# ── LLM ──
llm = None
try:
    llm = LLMClient(cfg.llm)
    print(f"[LLM] {cfg.llm.provider}/{cfg.llm.model} ready")
except Exception as e:
    print(f"[WARN] LLM not initialized: {e}")

# ── 记忆引擎 ──
memory_engine = MemoryEngine(llm, db) if llm else None

# ── 依赖注入 ──
init_auth_routes(db)
if llm:
    init_chat_routes(llm, db)
if memory_engine:
    init_memory_routes(db, memory_engine)

# ── App ──
app = FastAPI(
    title="🍮Chat",
    description="🍮Chat — Multi-user AI Chat Assistant",
    version="2.0.0",
)

# 静态文件
static_dir = str(cfg.static_dir)
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return JSONResponse({"message": "🍮Chat API is running", "version": "2.0.0", "docs": "/docs"})


@app.get("/login")
async def login_page():
    login_path = os.path.join(static_dir, "login.html")
    if os.path.isfile(login_path):
        return FileResponse(login_path)
    return JSONResponse({"message": "Login page not found"}, status_code=404)


# ── 路由 ──
app.include_router(chat_router)
app.include_router(auth_router)
app.include_router(memory_router)


# ── 微信回调（不需要 Auth） ──

@app.get("/wx/callback")
async def wx_verify(request: Request):
    return await wechat_verify(request)


@app.post("/wx/callback")
async def wx_callback(request: Request):
    if llm and db:
        return await wechat_callback(request, llm, db)
    return PlainTextResponse("service unavailable", status_code=503)


# ── Health ──

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "llm_ready": llm is not None,
        "db_ready": db is not None,
        "provider": cfg.llm.provider,
        "model": cfg.llm.model,
    }
