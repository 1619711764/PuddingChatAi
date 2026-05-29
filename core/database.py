# 多用户 SQLite 数据库封装 v2
# 替代 Supabase，支持用户注册/登录/数据隔离

import sqlite3
import uuid
import time
from core.config import AppConfig


class Database:
    """SQLite 多用户数据库"""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.db_path = cfg.db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            # 用户表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT DEFAULT '',
                    avatar_url TEXT DEFAULT '',
                    wechat_openid TEXT UNIQUE,
                    wechat_unionid TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            # 对话表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    title TEXT DEFAULT '新对话',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_user
                ON conversations(user_id, updated_at DESC)
            """)
            # 消息表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
                    content TEXT NOT NULL,
                    token_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_msg_conv
                ON messages(conversation_id, created_at)
            """)
            # 用户记忆表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source_conv_id TEXT REFERENCES conversations(id),
                    created_at REAL NOT NULL,
                    UNIQUE(user_id, key)
                )
            """)

    # ── Users ──

    def create_user(self, email: str, password_hash: str, display_name: str = "") -> dict:
        uid = str(uuid.uuid4())
        now = time.time()
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                    (uid, email.lower().strip(), password_hash, display_name or email.split("@")[0], "", now, now),
                )
            return {"id": uid, "email": email, "display_name": display_name}
        except sqlite3.IntegrityError:
            return None  # email already exists

    def get_user_by_email(self, email: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0], "email": row[1], "password_hash": row[2],
                "display_name": row[3], "avatar_url": row[4],
                "wechat_openid": row[5], "wechat_unionid": row[6],
            }

    def get_user_by_id(self, user_id: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                return None
            return {
                "id": row[0], "email": row[1], "password_hash": row[2],
                "display_name": row[3], "avatar_url": row[4],
                "wechat_openid": row[5], "wechat_unionid": row[6],
            }

    def get_user_by_wechat(self, openid: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE wechat_openid = ?", (openid,)
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0], "email": row[1], "password_hash": row[2],
                "display_name": row[3], "avatar_url": row[4],
                "wechat_openid": row[5], "wechat_unionid": row[6],
            }

    def update_user(self, user_id: str, data: dict):
        now = time.time()
        fields = []
        values = []
        for k, v in data.items():
            if k in ("display_name", "avatar_url", "wechat_openid", "wechat_unionid"):
                fields.append(f"{k} = ?")
                values.append(v)
        if not fields:
            return
        fields.append("updated_at = ?")
        values.append(now)
        values.append(user_id)
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values
            )

    def create_wechat_user(self, openid: str, unionid: str, nickname: str, avatar: str) -> dict:
        uid = str(uuid.uuid4())
        now = time.time()
        fake_email = f"wx_{openid[:12]}@wechat.local"
        import secrets
        pw = secrets.token_urlsafe(32)
        import bcrypt
        pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, fake_email, pw_hash, nickname, avatar, openid, unionid, now, now),
            )
        return {"id": uid, "email": fake_email, "display_name": nickname}

    def bind_wechat(self, user_id: str, openid: str, unionid: str, nickname: str, avatar: str):
        self.update_user(user_id, {
            "wechat_openid": openid,
            "wechat_unionid": unionid,
            "display_name": nickname,
            "avatar_url": avatar,
        })

    # ── Conversations ──

    def create_conversation(self, user_id: str, title: str = "新对话") -> dict:
        cid = str(uuid.uuid4())
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
                (cid, user_id, title, now, now),
            )
        return {"id": cid, "title": title, "user_id": user_id}

    def list_conversations(self, user_id: str, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]} for r in rows]

    def get_conversation(self, conv_id: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if not row:
                return None
            return {"id": row[0], "user_id": row[1], "title": row[2]}

    def update_title(self, conv_id: str, title: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, time.time(), conv_id),
            )

    def delete_conversation(self, conv_id: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    def touch_conversation(self, conv_id: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (time.time(), conv_id),
            )

    # ── Messages ──

    def add_message(self, conv_id: str, role: str, content: str, token_count: int = 0) -> dict:
        now = time.time()
        with self._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, token_count, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conv_id, role, content, token_count, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conv_id),
            )
            return {"id": cur.lastrowid}

    def get_messages(self, conv_id: str, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
                (conv_id, limit),
            ).fetchall()
        return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]

    def get_message_count(self, conv_id: str) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchone()
            return row[0] if row else 0

    # ── User Memories ──

    def get_memories(self, user_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_memories WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 30",
                (user_id,),
            ).fetchall()
        return [{"key": r[0], "value": r[1]} for r in rows]

    def upsert_memory(self, user_id: str, key: str, value: str, source_conv_id: str = None):
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_memories (user_id, key, value, source_conv_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, key, value, source_conv_id, now),
            )

    def delete_memory(self, user_id: str, key: str):
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM user_memories WHERE user_id = ? AND key = ?",
                (user_id, key),
            )

    def cleanup_expired(self):
        cutoff = time.time() - self.cfg.conversation_ttl_hours * 3600
        with self._get_conn() as conn:
            conn.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,))
