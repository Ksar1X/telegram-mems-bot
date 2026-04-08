import sqlite3
from datetime import datetime


class Database:
    def __init__(self, db_path="bot_data.db"):
        self.db_path = db_path
        self._create_table()

    def _create_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                         CREATE TABLE IF NOT EXISTS stats
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             user_id
                             INTEGER,
                             template_id
                             TEXT,
                             status
                             TEXT,
                             timestamp
                             DATETIME
                         )
                         """)
            conn.commit()

    def log_action(self, user_id: int, template_id: str, status: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO stats (user_id, template_id, status, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, template_id, status, datetime.now())
            )
            conn.commit()

    def get_today_stats(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Считаем паки за последние 24 часа
            cursor.execute(
                "SELECT COUNT(*) FROM stats WHERE status='success' AND timestamp > datetime('now', '-1 day')")
            packs_today = cursor.fetchone()[0]

            # Считаем уникальных юзеров
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM stats WHERE timestamp > datetime('now', '-1 day')")
            users_today = cursor.fetchone()[0]

            return packs_today, users_today


db = Database()