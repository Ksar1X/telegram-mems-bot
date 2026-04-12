import json
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── Telegram ─────────────────────────────────────────────────────────────
    BOT_TOKEN: str
    ADMIN_ID: str

    # ── Пути ─────────────────────────────────────────────────────────────────
    # Это путь к файлу
    TEMPLATES_CONFIG_PATH: str = "config.json"
    TMP_DIR: str = "temp_uploads"

    # ── Очередь задач ────────────────────────────────────────────────────────
    QUEUE_MAX_SIZE: int = 20
    WORKER_COUNT: int = 4

    @property
    def TEMPLATES_CONFIG(self) -> dict:
        """Этот метод автоматически читает JSON файл и возвращает его содержимое."""
        path = Path(self.TEMPLATES_CONFIG_PATH)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"templates": []}


settings = Settings()