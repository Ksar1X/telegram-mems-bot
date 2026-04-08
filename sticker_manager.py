import logging
from aiogram import Bot
from aiogram.types import FSInputFile, InputSticker
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)


class StickerManager:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def create_or_update_pack(self, user_id: int, sticker_paths: list[str]) -> str:
        bot_obj = await self.bot.get_me()
        bot_username = bot_obj.username
        name = f"user_{user_id}_by_{bot_username}"
        title = f"Нейро-пак для пользователя {user_id}"

        input_stickers = []
        for path in sticker_paths:
            st_format = "video" if path.lower().endswith(".webm") else "static"

            input_stickers.append(InputSticker(
                sticker=FSInputFile(path),
                emoji_list=["✨"],
                format=st_format
            ))

        if not input_stickers:
            return ""

        try:
            try:
                await self.bot.get_sticker_set(name=name)

                for sticker in input_stickers:
                    await self.bot.add_sticker_to_set(
                        user_id=user_id,
                        name=name,
                        sticker=sticker
                    )
                logger.info(f"Стикеры добавлены в пак {name}")

            except Exception as e:
                if "STICKERSET_INVALID" in str(e) or "400" in str(e):
                    pack_format = input_stickers[0].format

                    await self.bot.create_new_sticker_set(
                        user_id=user_id,
                        name=name,
                        title=title,
                        stickers=input_stickers,
                        sticker_format=pack_format
                    )
                    logger.info(f"Создан новый пак: {name}")
                else:
                    raise e

            return f"https://t.me/addstickers/{name}"

        except Exception as e:
            logger.error(f"Ошибка в StickerManager: {e}")
            return ""