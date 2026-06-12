# 🍮Chat Admin API — 管理面板后端

import os
import time
import sqlite3
from fastapi import APIRouter, HTTPException, Header
from core.database import Database
from core.config import AppConfig

router = APIRouter(prefix="/api/admin", tags=["admin"])

db: Database | None = None
cfg: AppConfig | None = None
ADMIN_KEY = os.getenv("ADMIN_KEY", "pudding-admin-2026")


def init_admin_routes(database: Database, config: AppConfig):
    global db, cfg, ADMIN_KEY
    db = database
    cfg = config
    ADMIN_KEY = os.getenv("ADMIN_KEY", "pudding-admin-2026")


def verify_admin(x_admin_key: str = Header(None, alias="X-Admin-Key")) -> str:
    if not x_admin_key or x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "管理员密钥错误")
    return x_admin_key


# ── 用户列表 ──

@router.get("/users")
async def admin_users(key: str = Header(None, alias="X-Admin-Key")):
    verify_admin(key)
    if not db:
        raise HTTPException(500, "数据库未初始化")

    conn = db._get_conn()
    rows = conn.execute(
        "SELECT id, email, display_name, avatar_url, register_ip, last_ip, "
        "wechat_openid, created_at, updated_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    users = []
    for r in rows:
        uid = r[0]
        # 获取对话数和消息数
        conn2 = db._get_conn()
        conv_count = conn2.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        msg_count = conn2.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)", (uid,)
        ).fetchone()[0]
        conn2.close()

        users.append({
            "id": r[0], "email": r[1], "display_name": r[2],
            "avatar_url": r[3], "register_ip": r[4] or "", "last_ip": r[5] or "",
            "wechat_bound": bool(r[6]),
            "created_at": r[7], "last_active": r[8],
            "conv_count": conv_count, "msg_count": msg_count,
        })

    return {"users": users, "total": len(users)}


# ── IP 归属地 ──

@router.get("/geo/{ip}")
async def geo_lookup(ip: str, key: str = Header(None, alias="X-Admin-Key")):
    verify_admin(key)
    import requests
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=5)
        data = resp.json()
        if data.get("status") == "success":
            return {
                "ip": ip,
                "country": data.get("country", ""),
                "region": data.get("regionName", ""),
                "city": data.get("city", ""),
                "isp": data.get("isp", ""),
            }
        return {"ip": ip, "error": data.get("message", "查询失败")}
    except Exception as e:
        return {"ip": ip, "error": str(e)}


# ── 统计 ──

@router.get("/stats")
async def admin_stats(key: str = Header(None, alias="X-Admin-Key")):
    verify_admin(key)
    if not db:
        raise HTTPException(500, "数据库未初始化")

    conn = db._get_conn()
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    mem_count = conn.execute("SELECT COUNT(*) FROM user_memories").fetchone()[0]
    conn.close()

    return {
        "users": user_count,
        "conversations": conv_count,
        "messages": msg_count,
        "memories": mem_count,
        "db_path": cfg.db_path if cfg else "",
        "version": "2.0.0",
    }


# ── 删除用户 ──

@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: str, key: str = Header(None, alias="X-Admin-Key")):
    verify_admin(key)
    if not db:
        raise HTTPException(500, "数据库未初始化")

    conn = db._get_conn()
    user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(404, "用户不存在")

    # 级联删除
    conn.execute("DELETE FROM user_memories WHERE user_id = ?", (user_id,))
    convs = conn.execute("SELECT id FROM conversations WHERE user_id = ?", (user_id,)).fetchall()
    for (cid,) in convs:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
    conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    return {"ok": True, "deleted": user[0]}


# ── 对话记录查看 ──

@router.get("/conversations")
async def admin_conversations(
    page: int = 1,
    limit: int = 50,
    user_id: str = "",
    key: str = Header(None, alias="X-Admin-Key"),
):
    verify_admin(key)
    if not db:
        raise HTTPException(500, "数据库未初始化")

    offset = max(0, (page - 1) * limit)

    conn = db._get_conn()
    if user_id:
        rows = conn.execute(
            """SELECT c.id, c.user_id, u.email, u.display_name, c.title,
                      c.created_at, c.updated_at
               FROM conversations c
               JOIN users u ON u.id = c.user_id
               WHERE c.user_id = ?
               ORDER BY c.updated_at DESC
               LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    else:
        rows = conn.execute(
            """SELECT c.id, c.user_id, u.email, u.display_name, c.title,
                      c.created_at, c.updated_at
               FROM conversations c
               JOIN users u ON u.id = c.user_id
               ORDER BY c.updated_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    conn.close()

    convs = []
    for r in rows:
        cid = r[0]
        conn2 = db._get_conn()
        msg_count = conn2.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (cid,)
        ).fetchone()[0]
        conn2.close()
        convs.append({
            "id": cid,
            "user_id": r[1],
            "user_email": r[2],
            "user_name": r[3],
            "title": r[4],
            "msg_count": msg_count,
            "created_at": r[5],
            "updated_at": r[6],
        })

    return {"conversations": convs, "total": total, "page": page, "limit": limit}


@router.get("/conversations/{conv_id}")
async def admin_conversation_detail(
    conv_id: str,
    key: str = Header(None, alias="X-Admin-Key"),
):
    verify_admin(key)
    if not db:
        raise HTTPException(500, "数据库未初始化")

    conn = db._get_conn()
    conv = conn.execute(
        """SELECT c.id, c.user_id, u.email, u.display_name, c.title, c.created_at, c.updated_at
           FROM conversations c
           JOIN users u ON u.id = c.user_id
           WHERE c.id = ?""",
        (conv_id,),
    ).fetchone()
    if not conv:
        conn.close()
        raise HTTPException(404, "对话不存在")

    msgs = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at",
        (conv_id,),
    ).fetchall()
    conn.close()

    return {
        "id": conv[0],
        "user_id": conv[1],
        "user_email": conv[2],
        "user_name": conv[3],
        "title": conv[4],
        "created_at": conv[5],
        "updated_at": conv[6],
        "messages": [
            {"role": m[0], "content": m[1], "created_at": m[2]}
            for m in msgs
        ],
    }
