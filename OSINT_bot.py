import asyncio
import logging
import os
import signal
import tempfile
import threading

from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

# --- Фиктивный веб-сервер для проверки работоспособности на Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def do_HEAD(self):
        # Отвечаем так же, как на GET, но без тела ответа
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
def start_health_server(port=10000):
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- Настройка логирования ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Конфигурация (безопасно через переменные окружения) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")

ALLOWED_USERS = []  # Можно задать список ID пользователей для ограничения доступа

# Состояния для ConversationHandler
CHOOSING_TOOL, TYPING_QUERY = range(2)

# --- Утилиты OSINT ---
OSINT_TOOLS: Dict[str, Dict[str, Any]] = {
    "maigret": {
        "name": "Maigret (поиск по никнейму)",
        "command": "maigret",
        "args": ["{query}"],
        "description": "Ищет никнейм на 3000+ сайтах.",
    },
    "holehe": {
        "name": "Holehe (проверка email)",
        "command": "holehe",
        "args": ["{query}"],
        "description": "Проверяет, на каких сервисах зарегистрирован email.",
    },
    "phoneinfoga": {
        "name": "PhoneInfoga (информация о номере)",
        "command": "phoneinfoga",
        "args": ["scan", "-n", "{query}"],
        "description": "Собирает базовую информацию о телефонном номере.",
    },
    "ipinfo": {
        "name": "IPinfo (информация об IP)",
        "command": "curl",
        "args": ["ipinfo.io/{query}"],
        "description": "Получает геолокацию и данные об IP-адресе.",
    },
}

# --- Функция проверки доступности утилит ---
def is_tool_available(name: str) -> bool:
    from shutil import which
    return which(name) is not None

# --- Базовые команды бота ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if ALLOWED_USERS and user.id not in ALLOWED_USERS:
        await update.message.reply_text("Извините, у вас нет доступа к этому боту.")
        return ConversationHandler.END

    keyboard = []
    for tool_key, tool_data in OSINT_TOOLS.items():
        cmd = tool_data["command"].split()[0]
        if is_tool_available(cmd):
            keyboard.append([f"/{tool_key}"])
        else:
            keyboard.append([f"/{tool_key} (не установлен)"])

    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋 Я OSINT-бот.\n\n"
        "Выберите инструмент из списка или используйте команды:\n"
        "/help - справка\n"
        "/list - список доступных инструментов",
    )
    return CHOOSING_TOOL

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Я умею запускать OSINT-утилиты прямо из Telegram.\n\n"
        "**Доступные команды:**\n"
        "/start - начать работу\n"
        "/list - список инструментов\n"
        "/cancel - отменить текущий поиск\n\n"
        "**Как использовать:**\n"
        "1. Выберите инструмент командой, например, `/sherlock`.\n"
        "2. Введите запрос (никнейм, email, телефон и т.д.).\n"
        "3. Дождитесь результата.\n"
    )
    await update.message.reply_text(help_text)

async def list_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tools_text = "**Доступные OSINT-инструменты:**\n\n"
    for tool_key, tool_data in OSINT_TOOLS.items():
        cmd = tool_data["command"].split()[0]
        available = "✅" if is_tool_available(cmd) else "❌"
        tools_text += f"{available} `/{tool_key}` - {tool_data['name']}\n"
        tools_text += f"   _{tool_data['description']}_\n\n"
    tools_text += "Команды, отмеченные ❌, не установлены в системе."
    await update.message.reply_text(tools_text, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# --- Основная логика выполнения OSINT-утилит ---
async def run_osint_tool(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         tool_key: str, query: str):
    tool_data = OSINT_TOOLS[tool_key]
    tool_name = tool_data["name"]
    command = tool_data["command"]
    args = [arg.format(query=query) for arg in tool_data["args"]]

    if not is_tool_available(command.split()[0]):
        await update.message.reply_text(
            f"❌ Утилита `{command.split()[0]}` не установлена в системе.\n"
            "Установите её и попробуйте снова.",
            parse_mode="Markdown"
        )
        return

    message = await update.message.reply_text(
        f"🔄 Идёт поиск с помощью **{tool_name}**...\nЗапрос: `{query}`",
        parse_mode="Markdown"
    )

    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as tmp_file:
            tmp_path = tmp_file.name

        process = await asyncio.create_subprocess_exec(
            command, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)

            with open(tmp_path, 'w') as f:
                if stdout:
                    f.write(stdout.decode('utf-8', errors='ignore'))
                if stderr:
                    f.write("\n--- STDERR ---\n")
                    f.write(stderr.decode('utf-8', errors='ignore'))

            if process.returncode != 0 and not stdout:
                err_msg = stderr.decode('utf-8', errors='ignore')[:1000]
                await message.edit_text(
                    f"❌ Ошибка при выполнении **{tool_name}**.\n\n`{err_msg}`",
                    parse_mode="Markdown"
                )
                return

            file_size = os.path.getsize(tmp_path)
            if file_size == 0:
                await message.edit_text(
                    f"⚠️ **{tool_name}** не вернул данных для запроса: `{query}`",
                    parse_mode="Markdown"
                )
            elif file_size < 4000:
                with open(tmp_path, 'r') as f:
                    result_text = f.read()
                await message.edit_text(
                    f"✅ **{tool_name}** завершил работу!\n\n```\n{result_text[:3500]}\n```",
                    parse_mode="Markdown"
                )
            else:
                await message.edit_text(
                    f"✅ **{tool_name}** завершил работу. Результат во вложении.",
                    parse_mode="Markdown"
                )
                with open(tmp_path, 'rb') as f:
                    await update.message.reply_document(
                        document=f,
                        filename=f"{tool_key}_{query}.txt",
                        caption=f"Результат для `{query}`"
                    )

        except asyncio.TimeoutError:
            await message.edit_text(
                f"⏱️ **{tool_name}** превысил время ожидания (60 секунд).\nПопробуйте другой запрос."
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if process.returncode is None:
                process.send_signal(signal.SIGINT)
                await asyncio.sleep(0.5)
                if process.returncode is None:
                    process.terminate()

    except Exception as e:
        logger.error(f"Ошибка при выполнении {tool_key}: {e}")
        await message.edit_text(
            f"❌ Произошла непредвиденная ошибка при работе с **{tool_name}**:\n`{str(e)}`",
            parse_mode="Markdown"
        )

# --- Обработчики диалога ---
async def tool_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tool_key = update.message.text.strip('/')
    if tool_key not in OSINT_TOOLS:
        await update.message.reply_text("Пожалуйста, выберите инструмент из списка.")
        return CHOOSING_TOOL

    context.user_data['tool'] = tool_key
    await update.message.reply_text(
        f"Вы выбрали **{OSINT_TOOLS[tool_key]['name']}**.\n\n"
        f"{OSINT_TOOLS[tool_key]['description']}\n\n"
        "Введите запрос (никнейм, email, телефон или IP):",
        parse_mode="Markdown"
    )
    return TYPING_QUERY

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.message.text.strip()
    tool_key = context.user_data.get('tool')

    if not tool_key:
        await update.message.reply_text("Сначала выберите инструмент командой /start.")
        return CHOOSING_TOOL

    await run_osint_tool(update, context, tool_key, query)

    await update.message.reply_text(
        "Хотите выполнить ещё один поиск? Выберите инструмент из списка или /cancel для завершения."
    )
    return CHOOSING_TOOL

# --- Запуск бота ---
def main() -> None:
    # Запускаем фиктивный веб-сервер в фоновом потоке (требование Render)
    threading.Thread(target=start_health_server, daemon=True).start()

    # Создаём приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Настраиваем ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_TOOL: [
                MessageHandler(filters.Regex(r'^/\w+$'), tool_selected),
            ],
            TYPING_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_tools))

    logger.info("Бот запущен на Render")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
