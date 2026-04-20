FROM python:3.11-slim

# Системные зависимости
RUN apt-get update && apt-get install -y curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Установка PhoneInfoga (бинарник)
RUN curl -sSL https://github.com/sundowndev/phoneinfoga/releases/latest/download/phoneinfoga_Linux_x86_64.tar.gz | tar -xz -C /usr/local/bin/ phoneinfoga

WORKDIR /app

# Копируем и устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем OSINT-утилиты как Python-пакеты
RUN pip install --no-cache-dir sherlock-project holehe

# blackbird может конфликтовать, поэтому заменяем на стабильный maigret
RUN pip install --no-cache-dir maigret

# Копируем код бота
COPY OSINT_bot.py .

CMD ["python", "OSINT_bot.py"]
