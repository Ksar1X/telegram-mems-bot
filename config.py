"""
config.py — Настройки приложения через pydantic-settings.
Значения читаются из переменных окружения или файла .env
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── Telegram ─────────────────────────────────────────────────────────────
    BOT_TOKEN: str                          # Обязательно! Из @BotFather

    # ── Пути ─────────────────────────────────────────────────────────────────
    TEMPLATES_CONFIG: str = "config.json"  # Путь к конфигу шаблонов
    TMP_DIR: str = "/tmp/facebot_uploads"  # Временные загрузки от пользователей

    # ── Очередь задач ────────────────────────────────────────────────────────
    QUEUE_MAX_SIZE: int = 20               # Максимальная глубина очереди
    WORKER_COUNT: int   = 2               # Кол-во параллельных воркеров (CPU/GPU)


settings = Settings()
