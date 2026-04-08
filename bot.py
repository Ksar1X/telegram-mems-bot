import asyncio
import logging
import os
import shutil
from datetime import datetime
import json

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

from config import settings
from database import db
from processor import FaceSwapProcessor
from sticker_manager import StickerManager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация компонентов
bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Глобальная очередь задач для воркеров
queue = asyncio.Queue()

# Инициализация процессора (движок нейронки) и менеджера стикеров
with open(settings.TEMPLATES_CONFIG_PATH, "r", encoding="utf-8") as f:
    config_data = json.load(f)
processor = FaceSwapProcessor(config_data)
sticker_manager = StickerManager(bot)


# --- Клавиатуры ---

def get_admin_kb():
    buttons = [
        [InlineKeyboardButton(text="♻️ Очистить TEMP", callback_data="admin_clear_temp")],
        [InlineKeyboardButton(text="📊 Обновить стат", callback_data="admin_refresh")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Хендлеры сообщений ---

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я нейро-бот для создания стикерпаков.\n"
        "Пришли мне свое фото (селфи), и я сделаю из него наборы мемов!"
    )


@router.message(Command("admin"))
async def admin_panel(message: Message):
    # Бронебойная проверка ID через строки
    if str(message.from_user.id) != str(settings.ADMIN_ID):
        await message.answer("❌ У вас нет прав доступа.")
        return

    packs, users = db.get_today_stats()
    text = (
        "🛠 **Панель управления**\n\n"
        f"✅ Создано паков (24ч): `{packs}`\n"
        f"👥 Уникальных юзеров (24ч): `{users}`"
    )
    await message.answer(text, reply_markup=get_admin_kb(), parse_mode="Markdown")


@router.message(F.photo)
async def handle_photo(message: Message):
    if not message.photo:
        return

    user_id = message.from_user.id
    photo = message.photo[-1]  # Берем самое качественное фото

    # Создаем папку для загрузок, если нет
    os.makedirs("temp_uploads", exist_ok=True)
    source_path = f"temp_uploads/{user_id}_{photo.file_unique_id}.jpg"

    # Скачиваем фото
    await bot.download(photo, destination=source_path)
    logger.info(f"Фото от user_id={user_id} сохранено: {source_path}")

    # Добавляем задачу в очередь для воркера
    await queue.put((user_id, source_path, message))
    await message.answer("📸 Фото получил! Начинаю магию над мемами... Это займет около минуты.")


# --- Обработка кнопок (Callback) ---

@router.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: CallbackQuery):
    if str(callback.from_user.id) != str(settings.ADMIN_ID):
        await callback.answer("Нет прав!", show_alert=True)
        return

    action = callback.data.split("_")[1]

    if action == "refresh":
        packs, users = db.get_today_stats()
        now = datetime.now().strftime("%H:%M:%S")
        text = (
            f"🛠 **Панель управления**\n\n"
            f"✅ Создано паков (24ч): `{packs}`\n"
            f"👥 Уникальных юзеров (24ч): `{users}`\n\n"
            f"🕒 Обновлено в: `{now}`"
        )
        try:
            await callback.message.edit_text(text, reply_markup=get_admin_kb(), parse_mode="Markdown")
        except Exception:
            pass  # Игнорируем, если текст не изменился
        await callback.answer("Обновлено")

    elif action == "clear_temp":
        folders = ["temp_stickers", "temp_uploads"]
        deleted_count = 0
        for folder in folders:
            if os.path.exists(folder):
                for filename in os.listdir(folder):
                    file_path = os.path.join(folder, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                            deleted_count += 1
                    except Exception:
                        pass
        await callback.answer(f"🧹 Очищено файлов: {deleted_count}", show_alert=True)


# --- Воркеры (Фоновая обработка) ---

async def process_task(user_id, source_path, message):
    try:
        # 1. Запускаем нейросеть
        sticker_paths = processor.process_all_templates(source_path, user_id)

        if not sticker_paths:
            await message.answer("😔 Не удалось найти лицо на фото. Попробуй другое фото.")
            db.log_action(user_id, "failed", "no_face")
            return

        # 2. Создаем/обновляем стикерпак в Telegram
        pack_url = await sticker_manager.create_or_update_pack(user_id, sticker_paths)

        if pack_url:
            await message.answer(f"🎉 Твой стикерпак готов!\n{pack_url}")
            db.log_action(user_id, "all_templates", "success")
        else:
            await message.answer("❌ Ошибка при создании стикерпака в Telegram.")

    except Exception as e:
        logger.exception(f"Ошибка в воркере: {e}")
        await message.answer("📛 Произошла техническая ошибка при обработке.")
    finally:
        # Удаляем исходное фото пользователя после обработки
        if os.path.exists(source_path):
            os.remove(source_path)


async def worker(name):
    logger.info(f"Воркер #{name} запущен")
    while True:
        user_id, source_path, message = await queue.get()
        await process_task(user_id, source_path, message)
        queue.task_done()


# --- Главная функция ---

async def main() -> None:
    # Подключаем роутер со всеми хендлерами
    dp.include_router(router)

    # Запускаем воркеры
    worker_tasks = [
        asyncio.create_task(worker(i))
        for i in range(settings.WORKER_COUNT)
    ]

    try:
        logger.info(f"Бот @{(await bot.get_me()).username} запущен!")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for t in worker_tasks:
            t.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")