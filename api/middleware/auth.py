# JWT 认证 — 使用 FastAPI 依赖注入（最可靠方式）

import os
import jwt
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

DEFAULT_SECRET = "aichat-local-jwt-secret-key-2026"
security = HTTPBearer(auto_error=False)

PUBLIC_PREFIXES = (
    "/health", "/docs", "/openapi.json", "/redoc",
    "/static", "/favicon.ico",
    "/api/auth/login", "/api/auth/register",
    "/api/auth/wechat/qrcode", "/api/auth/wechat/callback",
    "/wx/callback",
)
PUBLIC_EXACT = {"/login", "/"}


def is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """FastAPI 依赖：验证 JWT 并返回 user_id"""
    path = request.url.path

    # 公开路径跳过认证
    if is_public_path(path):
        return None

    if not credentials:
        raise HTTPException(401, "缺少认证令牌")

    token = credentials.credentials
    jwt_secret = os.getenv("JWT_SECRET", DEFAULT_SECRET)

    try:
        payload = jwt.decode(
            token, jwt_secret, algorithms=["HS256"],
            options={"verify_exp": True},
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "无效的认证令牌")

        # 同时设置 request.state 方便其他代码使用
        request.state.user_id = user_id
        request.state.user_email = payload.get("email", "")
        return user_id

    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "令牌已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "无效的认证令牌")


def get_user_id(request: Request) -> str:
    """从 request.state 获取当前用户 ID（需要在路由中先调用 get_current_user）"""
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "未登录")
    return uid
