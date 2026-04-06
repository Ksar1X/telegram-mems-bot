# Dockerfile для production-деплоя
# Используем образ с предустановленными CV-библиотеками

FROM python:3.11-slim

# Системные зависимости для OpenCV и InsightFace
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# InsightFace скачает модели в ~/.insightface при первом запуске.
# Для prod рекомендуется предварительно скачать и примонтировать:
# docker run -v /host/models:/root/.insightface ...

CMD ["python", "bot.py"]
