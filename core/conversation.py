# 对话管理器 — SQLite 持久化多轮对话

import sqlite3
import json
import uuid
import time
from datetime import datetime, timedelta
from core.config import AppConfig


class ConversationManager:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.cfg.db_path)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT DEFAULT '新对话',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_updated
                ON conversations(updated_at DESC)
            """)

    def create(self, title: str = "新对话") -> str:
        cid = str(uuid.uuid4())[:8]
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
                (cid, title, now, now, "[]"),
            )
        return cid

    def add_message(self, conv_id: str, role: str, content: str):
        now = time.time()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT messages FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if not row:
                return False
            msgs = json.loads(row[0])
            msgs.append({"role": role, "content": content, "time": now})
            # 只保留最近 N 条
            msgs = msgs[-self.cfg.max_history_messages * 2:]
            conn.execute(
                "UPDATE conversations SET messages = ?, updated_at = ? WHERE id = ?",
                (json.dumps(msgs, ensure_ascii=False), now, conv_id),
            )
        return True

    def get_messages(self, conv_id: str, limit: int = None) -> list[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT messages FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if not row:
                return []
            msgs = json.loads(row[0])
            if limit:
                msgs = msgs[-limit:]
        return msgs

    def list_conversations(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 50"
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
            for r in rows
        ]

    def update_title(self, conv_id: str, title: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, conv_id),
            )

    def delete(self, conv_id: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    def cleanup_expired(self):
        cutoff = time.time() - self.cfg.conversation_ttl_hours * 3600
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM conversations WHERE updated_at < ?", (cutoff,)
            )

    def auto_title(self, conv_id: str, first_message: str) -> str:
        """根据第一条消息自动生成对话标题"""
        title = first_message[:20].replace("\n", " ")
        if len(first_message) > 20:
            title += "..."
        self.update_title(conv_id, title)
        return title
