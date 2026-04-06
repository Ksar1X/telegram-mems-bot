"""
bot.py — Точка входа. Регистрирует хэндлеры, запускает очередь задач и поллинг.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

from config import settings
from processor import FaceSwapProcessor
from sticker_manager import StickerManager

# ─── Логирование ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Инициализация ───────────────────────────────────────────────────────────
bot = Bot(token=settings.BOT_TOKEN)
dp  = Dispatcher()

# Очередь задач: каждая задача — tuple (user_id, путь к фото)
task_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.QUEUE_MAX_SIZE)

processor      = FaceSwapProcessor(settings.TEMPLATES_CONFIG)
sticker_manager = StickerManager(bot)


# ─── Хэндлеры ────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие и краткая инструкция."""
    await message.answer(
        "👋 Привет! Я создам персональный стикерпак с твоим лицом.\n\n"
        "📸 Просто отправь мне чёткое фото лица (желательно анфас) — "
        "и я подменю лицо на набор мемов, а потом создам стикерпак в Telegram."
    )


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """
    Принимаем фото, скачиваем самую большую версию
    и ставим задачу в очередь.
    """
    if task_queue.full():
        await message.answer("⏳ Очередь переполнена, попробуй через минуту.")
        return

    # Берём фото с максимальным разрешением (последний элемент списка)
    photo = message.photo[-1]
    user_id = message.from_user.id

    # Временный файл для хранения загруженного фото
    tmp_dir = Path(settings.TMP_DIR)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    source_path = tmp_dir / f"{user_id}_{uuid.uuid4().hex}.jpg"

    await bot.download(photo, destination=source_path)
    logger.info("Фото от user_id=%s сохранено: %s", user_id, source_path)

    await task_queue.put((user_id, source_path, message))
    await message.answer("✅ Фото получено! Обрабатываю… это займёт ~10–30 секунд.")


# ─── Воркер очереди ──────────────────────────────────────────────────────────

async def worker(worker_id: int) -> None:
    """
    Фоновый воркер. Берёт задачи из очереди и обрабатывает их последовательно,
    чтобы не перегружать CPU/GPU.
    Для масштабирования можно запустить несколько воркеров.
    """
    logger.info("Воркер #%d запущен", worker_id)
    while True:
        user_id, source_path, message = await task_queue.get()
        try:
            await process_task(user_id, source_path, message)
        except Exception as exc:
            logger.exception("Ошибка в воркере #%d: %s", worker_id, exc)
            await message.answer("❌ Что-то пошло не так при обработке. Попробуй снова.")
        finally:
            # Удаляем временный файл источника
            source_path.unlink(missing_ok=True)
            task_queue.task_done()


async def process_task(user_id: int, source_path: Path, message: Message) -> None:
    """
    Полный пайплайн обработки одной задачи:
    1. Face Swap по всем шаблонам
    2. Создание стикерпака через Telegram API
    3. Отправка ссылки пользователю
    """
    # Запускаем CPU-тяжёлую обработку в пуле потоков, чтобы не блокировать event loop
    loop = asyncio.get_running_loop()
    sticker_paths = await loop.run_in_executor(
        None,  # использует ThreadPoolExecutor по умолчанию
        processor.process_all_templates,
        source_path,
        user_id,
    )

    if not sticker_paths:
        await message.answer("😕 Не удалось найти лицо на фото. Попробуй другое — "
                              "лучше анфас при хорошем освещении.")
        return

    # Создаём стикерпак
    pack_name, pack_link = await sticker_manager.create_sticker_set(
        user_id=user_id,
        sticker_paths=sticker_paths,
        title=f"My Meme Pack by @{(await bot.get_me()).username}",
    )

    # Чистим временные стикеры
    for p in sticker_paths:
        Path(p).unlink(missing_ok=True)

    await message.answer(
        f"🎉 Стикерпак готов!\n"
        f"👉 <a href='https://t.me/addstickers/{pack_name}'>Добавить стикерпак</a>",
        parse_mode="HTML",
    )
    logger.info("Стикерпак '%s' создан для user_id=%s", pack_name, user_id)


# ─── Запуск ──────────────────────────────────────────────────────────────────

async def main() -> None:
    # Запускаем N воркеров параллельно
    worker_tasks = [
        asyncio.create_task(worker(i))
        for i in range(settings.WORKER_COUNT)
    ]

    try:
        logger.info("Бот запущен. Воркеров: %d", settings.WORKER_COUNT)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # При остановке отменяем воркеры
        for t in worker_tasks:
            t.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
