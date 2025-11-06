# Dockerfile для Telegram бота игры пар
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Копируем файлы требований
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем директорию для логов
RUN mkdir -p logs

# Создаем пользователя для безопасности
RUN useradd -m -u 1000 telegram-bot && \
    chown -R telegram-bot:telegram-bot /app

# Переключаемся на пользователя telegram-bot
USER telegram-bot

# Открываем порт (если нужен веб-интерфейс)
EXPOSE 8080

# Команда запуска
CMD ["python", "main.py"]