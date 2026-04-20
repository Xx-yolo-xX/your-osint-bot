FROM python:3.11-slim

# Установка системных утилит и очистка кэша apt
RUN apt-get update && apt-get install -y curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Установка PhoneInfoga (бинарник)
RUN curl -sSL https://github.com/sundowndev/phoneinfoga/releases/latest/download/phoneinfoga_Linux_x86_64.tar.gz | tar -xz -C /usr/local/bin/ phoneinfoga

WORKDIR /app

# Копируем зависимости и устанавливаем
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY OSINT_bot.py .

# Запускаем бота
CMD ["python", "OSINT_bot.py"]
