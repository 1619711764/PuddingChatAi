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


# ── IP 工具 ──

def get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（支持代理/隧道）"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    client = request.client
    return client.host if client else "unknown"


# ── JWT 工具 ──

def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + jwt_expire_hours * 3600,
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def create_refresh_token(user_id: str) -> str:
    """30-day refresh token"""
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": int(time.time()),
        "exp": int(time.time()) + 30 * 24 * 3600,
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


class RefreshRequest(BaseModel):
    refresh_token: str


# ── 注册 ──

@router.post("/register")
async def register(req: RegisterRequest, request: Request):
    if not db:
        raise HTTPException(500, "数据库未初始化")

    ip = get_client_ip(request)
    pw_hash = hash_password(req.password)
    user = db.create_user(req.email, pw_hash, req.display_name, register_ip=ip)

    if user is None:
        raise HTTPException(409, "该邮箱已注册")

    token = create_token(user["id"], user["email"])
    refresh = create_refresh_token(user["id"])
    return {
        "ok": True,
        "user_id": user["id"],
        "email": user["email"],
        "access_token": token,
        "refresh_token": refresh,
        "expires_in": jwt_expire_hours * 3600,
    }


# ── 登录 ──

@router.post("/login")
async def login(req: LoginRequest, request: Request):
    if not db:
        raise HTTPException(500, "数据库未初始化")

    user = db.get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "邮箱或密码错误")

    ip = get_client_ip(request)
    db.update_last_ip(user["id"], ip)

    token = create_token(user["id"], user["email"])
    refresh = create_refresh_token(user["id"])
    return {
        "ok": True,
        "access_token": token,
        "refresh_token": refresh,
        "expires_in": jwt_expire_hours * 3600,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "avatar_url": user["avatar_url"],
        },
    }


# ── Token 刷新 ──

@router.post("/refresh")
async def refresh_token(req: RefreshRequest):
    """使用 refresh_token 获取新的 access_token"""
    if not db:
        raise HTTPException(500, "数据库未初始化")

    try:
        payload = jwt.decode(
            req.refresh_token, jwt_secret, algorithms=["HS256"],
            options={"verify_exp": True},
        )
        if payload.get("type") != "refresh":
            raise HTTPException(401, "无效的刷新令牌")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "无效的刷新令牌")

        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(401, "用户不存在")

        new_access = create_token(user_id, user["email"])
        new_refresh = create_refresh_token(user_id)
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "expires_in": jwt_expire_hours * 3600,
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "刷新令牌已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "无效的刷新令牌")


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
        refresh = create_refresh_token(user["id"])
        return {"access_token": token, "refresh_token": refresh, "user_id": user["id"], "is_new": False}
    else:
        user = db.create_wechat_user(openid, unionid, nickname, avatar)
        token = create_token(user["id"], user["email"])
        refresh = create_refresh_token(user["id"])
        return {"access_token": token, "refresh_token": refresh, "user_id": user["id"], "is_new": True}


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


# ── 更新个人资料 ──

class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(None, max_length=64)


@router.patch("/me")
async def update_profile(req: UpdateProfileRequest, user_id: str = Depends(get_current_user)):
    """更新当前用户资料（昵称等）"""
    if not user_id:
        raise HTTPException(401, "未登录")
    if not db:
        raise HTTPException(500, "数据库未初始化")

    updates = {}
    if req.display_name is not None:
        name = req.display_name.strip()
        if name:
            updates["display_name"] = name

    if updates:
        db.update_user(user_id, updates)

    user = db.get_user_by_id(user_id)
    return {
        "ok": True,
        "display_name": user.get("display_name", "") if user else "",
        "avatar_url": user.get("avatar_url", "") if user else "",
    }


# ── 头像上传 ──

from fastapi import UploadFile
import uuid as uuid_mod


AVATAR_DIR = __import__('pathlib').Path(__file__).parent.parent.parent / "static" / "avatars"


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile,
    user_id: str = Depends(get_current_user),
):
    """上传用户头像"""
    if not user_id:
        raise HTTPException(401, "未登录")
    if not db:
        raise HTTPException(500, "数据库未初始化")

    try:
        # 校验文件类型
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        content_type = file.content_type or ""
        if content_type not in allowed:
            # 尝试从文件名判断
            ext_check = (file.filename or "").rsplit(".", 1)[-1].lower()
            mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
            if ext_check in mime_map:
                content_type = mime_map[ext_check]
            else:
                raise HTTPException(400, f"仅支持 JPEG/PNG/GIF/WebP (收到: {ext_check})")

        # 校验大小 (5MB)
        contents = await file.read()
        if not contents:
            raise HTTPException(400, "文件内容为空")
        if len(contents) > 5 * 1024 * 1024:
            raise HTTPException(400, "图片大小不能超过 5MB")

        # 保存文件
        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        ext = (file.filename or "avatar").rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
            ext = "png"
        filename = f"{user_id[:8]}_{uuid_mod.uuid4().hex[:8]}.{ext}"
        filepath = AVATAR_DIR / filename

        with open(filepath, "wb") as f:
            f.write(contents)

        # 更新数据库
        avatar_url = f"/static/avatars/{filename}"
        db.update_user(user_id, {"avatar_url": avatar_url})

        return {"ok": True, "avatar_url": avatar_url}

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"上传失败: {str(e)}")
