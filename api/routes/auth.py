# Auth 路由 v2 — 本地 bcrypt + JWT

import os
import time
import secrets
import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from core.database import Database
from core.config import AppConfig

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 由 main.py 注入
db: Database | None = None
jwt_secret: str = ""
jwt_expire_hours: int = 168  # 7 天


DEFAULT_JWT_SECRET = "aichat-local-jwt-secret-key-2026"


def init_auth_routes(database: Database):
    global db, jwt_secret, jwt_expire_hours
    db = database
    import os as _os
    jwt_secret = _os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
    jwt_expire_hours = int(_os.getenv("JWT_EXPIRE_HOURS", "168"))


# ── JWT 工具 ──

def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + jwt_expire_hours * 3600,
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ── 请求模型 ──

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


# ── 注册 ──

@router.post("/register")
async def register(req: RegisterRequest):
    if not db:
        raise HTTPException(500, "数据库未初始化")

    pw_hash = hash_password(req.password)
    user = db.create_user(req.email, pw_hash, req.display_name)

    if user is None:
        raise HTTPException(409, "该邮箱已注册")

    token = create_token(user["id"], user["email"])
    return {
        "ok": True,
        "user_id": user["id"],
        "email": user["email"],
        "access_token": token,
    }


# ── 登录 ──

@router.post("/login")
async def login(req: LoginRequest):
    if not db:
        raise HTTPException(500, "数据库未初始化")

    user = db.get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "邮箱或密码错误")

    token = create_token(user["id"], user["email"])
    return {
        "ok": True,
        "access_token": token,
        "expires_in": jwt_expire_hours * 3600,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "avatar_url": user["avatar_url"],
        },
    }


# ── 微信扫码登录 ──

WX_APP_ID = os.getenv("WX_APP_ID", "")
WX_APP_SECRET = os.getenv("WX_APP_SECRET", "")


@router.get("/wechat/qrcode")
async def wechat_qrcode():
    """生成微信扫码登录 URL"""
    if not WX_APP_ID:
        raise HTTPException(501, "微信登录未配置")

    state = secrets.token_urlsafe(32)
    redirect_uri = os.getenv("WX_REDIRECT_URI", "")
    if not redirect_uri:
        raise HTTPException(500, "未配置 WX_REDIRECT_URI")

    qr_url = (
        f"https://open.weixin.qq.com/connect/qrconnect"
        f"?appid={WX_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=snsapi_login"
        f"&state={state}"
        f"#wechat_redirect"
    )
    return {"qr_url": qr_url, "state": state}


@router.get("/wechat/callback")
async def wechat_callback(code: str, state: str = ""):
    """微信扫码回调"""
    if not WX_APP_ID or not WX_APP_SECRET:
        raise HTTPException(501, "微信登录未配置")
    if not db:
        raise HTTPException(500, "数据库未初始化")

    import httpx

    # 1. 用 code 换 access_token
    async with httpx.AsyncClient() as client:
        token_res = await client.get(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            params={
                "appid": WX_APP_ID,
                "secret": WX_APP_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        token_data = token_res.json()

    if "errcode" in token_data and token_data["errcode"] != 0:
        raise HTTPException(400, f"微信授权失败: {token_data.get('errmsg', '')}")

    openid = token_data["openid"]
    unionid = token_data.get("unionid", "")
    access_token = token_data["access_token"]

    # 2. 获取用户信息
    async with httpx.AsyncClient() as client:
        info_res = await client.get(
            "https://api.weixin.qq.com/sns/userinfo",
            params={"access_token": access_token, "openid": openid},
        )
        wx_info = info_res.json()

    nickname = wx_info.get("nickname", f"微信用户{openid[:6]}")
    avatar = wx_info.get("headimgurl", "")

    # 3. 查找或创建用户
    user = db.get_user_by_wechat(openid)
    if user:
        token = create_token(user["id"], user["email"])
        return {"access_token": token, "user_id": user["id"], "is_new": False}
    else:
        user = db.create_wechat_user(openid, unionid, nickname, avatar)
        token = create_token(user["id"], user["email"])
        return {"access_token": token, "user_id": user["id"], "is_new": True}


# ── 用户信息 ──

from api.middleware.auth import get_current_user


@router.get("/me")
async def get_me(request: Request, user_id: str = Depends(get_current_user)):
    """获取当前登录用户信息"""
    if not user_id:
        raise HTTPException(401, "未登录")

    user = db.get_user_by_id(user_id) if db else None
    return {
        "user_id": user_id,
        "email": getattr(request.state, "user_email", "") or (user.get("email", "") if user else ""),
        "display_name": user.get("display_name", "") if user else "",
        "avatar_url": user.get("avatar_url", "") if user else "",
        "wechat_bound": bool(user.get("wechat_openid")) if user else False,
    }
