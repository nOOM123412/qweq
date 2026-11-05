FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    DATA_DIR=/app/data

WORKDIR /app

# Зависимости ставим отдельным слоем — быстрее пересборка
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Код приложения
COPY . .

# Каталог для постоянных данных (SQLite). Монтируется как volume на Bothost
RUN mkdir -p /app/data

EXPOSE 3000

CMD ["python", "main.py"]
