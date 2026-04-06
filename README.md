# 🎭 FaceSticker Bot

Telegram-бот, который создаёт персональный стикерпак с лицом пользователя
на основе популярных мем-шаблонов.

## Архитектура проекта

```
stickerbot/
├── bot.py              — точка входа, хэндлеры aiogram, очередь задач
├── processor.py        — Face Swap (InsightFace / простой фоллбэк)
├── sticker_manager.py  — создание стикерпаков через Telegram API
├── config.py           — настройки через pydantic-settings / .env
├── config.json         — пути к шаблонам и координаты лиц
├── templates/          — PNG-шаблоны мемов (512×512 рекомендуется)
│   ├── distracted_boyfriend.png
│   ├── this_is_fine.png
│   ├── drake.png
│   ├── gigachad.png
│   └── math_lady.png
├── requirements.txt
├── Dockerfile
└── .env.example
```

## Быстрый старт

```bash
# 1. Клонируйте репозиторий и перейдите в папку
cd stickerbot

# 2. Создайте виртуальное окружение
python -m venv .venv && source .venv/bin/activate

# 3. Установите зависимости
pip install -r requirements.txt

# 4. Настройте переменные окружения
cp .env.example .env
# Откройте .env и вставьте токен бота от @BotFather

# 5. Добавьте шаблоны в папку templates/
# (PNG-файлы с лицами, желательно анфас, минимум 512×512)

# 6. Запустите бота
python bot.py
```

## Конфигурация шаблонов (config.json)

| Поле | Описание |
|---|---|
| `backend` | `"insightface"` (нейросеть) или `"paste_simple"` (фоллбэк) |
| `onnx_providers` | `["CUDAExecutionProvider", "CPUExecutionProvider"]` |
| `templates[].path` | Путь к PNG-шаблону |
| `templates[].face_region` | Область для вставки лица (только для `paste_simple`) |
| `templates[].emoji` | Эмодзи стикера в Telegram |

## Модели InsightFace

При первом запуске `insightface` автоматически скачивает:
- `buffalo_l` — детектор лиц (~300 MB, в `~/.insightface/models/`)
- `inswapper_128.onnx` — модель свапа (~500 MB)

Для отключения автозагрузки — положите модели вручную в `~/.insightface/models/`.

## Масштабирование

- **Несколько воркеров**: измените `WORKER_COUNT` в `.env`
- **GPU**: замените `onnxruntime` на `onnxruntime-gpu` в requirements.txt
- **Webhook вместо polling**: замените `dp.start_polling()` на `dp.start_webhook()`
- **Celery**: замените `asyncio.Queue` на Celery + Redis для распределённой обработки
