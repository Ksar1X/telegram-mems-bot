"""
sticker_manager.py — Создание и управление стикерпаками через Telegram Bot API.

Telegram требует уникальное имя пака вида: {что-то}_by_{botusername}
Один стикерпак = до 120 стикеров. Здесь мы создаём новый пак при каждом запросе
(можно расширить логику: добавлять стикеры в существующий пак пользователя).
"""

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import (
    FSInputFile,
    InputSticker,
)

logger = logging.getLogger(__name__)


class StickerManager:
    """Управляет жизненным циклом стикерпаков конкретного бота."""

    def __init__(self, bot: Bot):
        self._bot = bot

    async def create_sticker_set(
        self,
        user_id: int,
        sticker_paths: list[str],
        title: str = "My Face Pack",
    ) -> tuple[str, str]:
        """
        Создаёт новый стикерпак и возвращает (name, link).

        :param user_id:       Telegram user_id владельца пака.
        :param sticker_paths: Пути к готовым PNG-файлам (512×512).
        :param title:         Отображаемое название пака (до 64 символов).
        :returns:             (pack_name, t.me/addstickers/pack_name)
        """
        bot_info  = await self._bot.get_me()
        bot_username = bot_info.username

        # Имя пака должно быть уникальным и заканчиваться на _by_{botusername}
        import uuid as _uuid
        short_id  = _uuid.uuid4().hex[:8]
        pack_name = f"memes_{short_id}_by_{bot_username}"

        if not sticker_paths:
            raise ValueError("sticker_paths не может быть пустым.")

        # ── Формируем список InputSticker ────────────────────────────────────
        stickers: list[InputSticker] = []
        for path in sticker_paths:
            stickers.append(
                InputSticker(
                    sticker=FSInputFile(path),
                    emoji_list=["😂"],   # Можно расширить: разные эмодзи для разных мемов
                    format="static",     # "static" | "animated" | "video"
                )
            )

        # ── Создаём пак ──────────────────────────────────────────────────────
        await self._bot.create_new_sticker_set(
            user_id=user_id,
            name=pack_name,
            title=title[:64],    # Telegram ограничивает 64 символами
            stickers=stickers,
        )

        pack_link = f"https://t.me/addstickers/{pack_name}"
        logger.info("Стикерпак создан: %s", pack_link)
        return pack_name, pack_link

    async def add_stickers_to_set(
        self,
        pack_name: str,
        user_id: int,
        sticker_paths: list[str],
    ) -> None:
        """
        Добавляет стикеры в существующий пак (для расширения функциональности).
        Telegram позволяет максимум 120 стикеров в одном паке.
        """
        for path in sticker_paths:
            await self._bot.add_sticker_to_set(
                user_id=user_id,
                name=pack_name,
                sticker=InputSticker(
                    sticker=FSInputFile(path),
                    emoji_list=["😂"],
                    format="static",
                ),
            )

    async def delete_sticker_set(self, pack_name: str) -> None:
        """Удаляет стикерпак (если нужна ротация / очистка старых паков)."""
        await self._bot.delete_sticker_set(name=pack_name)
        logger.info("Стикерпак '%s' удалён.", pack_name)
