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
                    register_ip TEXT DEFAULT '',
                    last_ip TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            # auto-add columns for existing DBs
            try:
                conn.execute("ALTER TABLE users ADD COLUMN register_ip TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE users ADD COLUMN last_ip TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
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
            # AI 人格表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_personas (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    style_tone TEXT DEFAULT 'balanced',
                    style_length TEXT DEFAULT 'normal',
                    catchphrases TEXT DEFAULT '',
                    taboos TEXT DEFAULT '',
                    system_prompt TEXT NOT NULL,
                    few_shot_examples TEXT DEFAULT '',
                    created_by TEXT DEFAULT 'system',
                    is_system INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    usage_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            # 对话摘要表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conv_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    summary TEXT NOT NULL,
                    key_topics TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    UNIQUE(conversation_id)
                )
            """)
            # 风格采集表 — 用于蒸馏 AI 人格
            conn.execute("""
                CREATE TABLE IF NOT EXISTS style_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    message TEXT NOT NULL,
                    persona_id TEXT REFERENCES ai_personas(id),
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_style_user
                ON style_samples(user_id, created_at)
            """)
            # 用户-人格绑定表（特定用户强制使用指定人格）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_persona_overrides (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    persona_id TEXT NOT NULL REFERENCES ai_personas(id),
                    reason TEXT DEFAULT '',
                    created_at REAL NOT NULL
                )
            """)

    # ── Users ──

    def create_user(self, email: str, password_hash: str, display_name: str = "", register_ip: str = "") -> dict:
        uid = str(uuid.uuid4())
        now = time.time()
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO users (id, email, password_hash, display_name, avatar_url, wechat_openid, wechat_unionid, register_ip, last_ip, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)",
                    (uid, email.lower().strip(), password_hash, display_name or email.split("@")[0], "", register_ip, register_ip, now, now),
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
                "register_ip": row[7] if len(row) > 7 else "",
                "last_ip": row[8] if len(row) > 8 else "",
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
                "register_ip": row[7] if len(row) > 7 else "",
                "last_ip": row[8] if len(row) > 8 else "",
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
                "register_ip": row[7] if len(row) > 7 else "",
                "last_ip": row[8] if len(row) > 8 else "",
            }

    def update_last_ip(self, user_id: str, ip: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_ip = ?, updated_at = ? WHERE id = ?",
                (ip, time.time(), user_id),
            )

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
                "INSERT INTO users (id, email, password_hash, display_name, avatar_url, wechat_openid, wechat_unionid, register_ip, last_ip, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, ?)",
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

    # ── AI Personas ──

    def create_persona(self, data: dict) -> str:
        import uuid as _uuid
        pid = str(_uuid.uuid4())
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO ai_personas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, data["name"], data.get("description", ""),
                 data.get("style_tone", "balanced"), data.get("style_length", "normal"),
                 data.get("catchphrases", ""), data.get("taboos", ""),
                 data["system_prompt"], data.get("few_shot_examples", ""),
                 data.get("created_by", "system"), data.get("is_system", 0),
                 1, 0, now, now),
            )
        return pid

    def get_personas(self, include_system: bool = True) -> list[dict]:
        with self._get_conn() as conn:
            sql = "SELECT * FROM ai_personas WHERE is_active=1"
            if not include_system:
                sql += " AND is_system=0"
            sql += " ORDER BY is_system DESC, usage_count DESC"
            rows = conn.execute(sql).fetchall()
        return [self._persona_dict(r) for r in rows]

    def get_persona(self, persona_id: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM ai_personas WHERE id=?", (persona_id,)).fetchone()
            return self._persona_dict(row) if row else None

    def get_default_persona(self) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM ai_personas WHERE is_active=1 ORDER BY is_system DESC, usage_count DESC LIMIT 1"
            ).fetchone()
            return self._persona_dict(row) if row else None

    def increment_persona_usage(self, persona_id: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE ai_personas SET usage_count=usage_count+1 WHERE id=?", (persona_id,))

    def _persona_dict(self, row) -> dict:
        return {
            "id": row[0], "name": row[1], "description": row[2],
            "style_tone": row[3], "style_length": row[4],
            "catchphrases": row[5], "taboos": row[6],
            "system_prompt": row[7], "few_shot_examples": row[8],
            "created_by": row[9], "is_system": bool(row[10]),
            "is_active": bool(row[11]), "usage_count": row[12],
        }

    # ── User-Persona Overrides ──

    def get_user_persona_override(self, user_id: str) -> str | None:
        """返回用户的强制人格 ID，无绑定时返回 None"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT persona_id FROM user_persona_overrides WHERE user_id=?",
                (user_id,),
            ).fetchone()
            return row[0] if row else None

    def set_user_persona_override(self, user_id: str, persona_id: str, reason: str = ""):
        """绑定用户到指定人格"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_persona_overrides VALUES (?, ?, ?, ?)",
                (user_id, persona_id, reason, time.time()),
            )

    def remove_user_persona_override(self, user_id: str):
        """解除用户人格绑定"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM user_persona_overrides WHERE user_id=?", (user_id,))

    def get_persona_bound_user(self, persona_id: str) -> str | None:
        """返回被绑定到此人格的用户 ID，无绑定时返回 None"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT user_id FROM user_persona_overrides WHERE persona_id=?",
                (persona_id,),
            ).fetchone()
            return row[0] if row else None

    # ── Conversation Summaries ──

    def save_summary(self, conv_id: str, summary: str, key_topics: str = ""):
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO conv_summaries VALUES (?, ?, ?, ?, ?)",
                (None, conv_id, summary, key_topics, now),
            )

    def get_recent_summaries(self, user_id: str, limit: int = 5) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT cs.summary, cs.key_topics FROM conv_summaries cs "
                "JOIN conversations c ON cs.conversation_id = c.id "
                "WHERE c.user_id = ? ORDER BY cs.created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [{"summary": r[0], "key_topics": r[1]} for r in rows]

    # ── 风格采集 ──

    def add_style_sample(self, user_id: str, message: str, persona_id: str = None):
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO style_samples (user_id, message, persona_id, created_at) VALUES (?, ?, ?, ?)",
                (user_id, message, persona_id, now),
            )

    def get_style_samples(self, user_id: str, limit: int = 200) -> list[str]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT message FROM style_samples WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [r[0] for r in rows]

    def count_style_samples(self, user_id: str) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM style_samples WHERE user_id=?", (user_id,)
            ).fetchone()
        return row[0] if row else 0

    def cleanup_expired(self):
        cutoff = time.time() - self.cfg.conversation_ttl_hours * 3600
        with self._get_conn() as conn:
            conn.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,))
