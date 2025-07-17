import os
import json
import logging
import requests
import asyncio
from datetime import datetime
from logging.handlers import RotatingFileHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    CallbackContext, 
    CallbackQueryHandler,
    JobQueue
)
from collections import defaultdict
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # Ключ теперь в .env

# Проверка наличия обязательных ключей
if not TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Не найдены обязательные переменные окружения! Проверьте .env файл.")

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Форматтер для логов
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Логирование в файл с ротацией
file_handler = RotatingFileHandler(
    'bot.log', 
    maxBytes=5*1024*1024,  # 5 MB
    backupCount=3
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Логирование в консоль
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Уменьшаем логирование сторонних библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)

# Создаем папки для хранения данных
os.makedirs("user_chats", exist_ok=True)

# Конфигурация
GROUP_INVITE_LINK = "https://t.me/+zoLEVViEZ7RkMzIy"
GROUP_ID = "-1002331837814"
DAILY_INCREMENT = 2
MAX_LIMIT = 6

# Структуры данных
user_data = defaultdict(lambda: {
    "requests_used": 0,
    "last_request_date": None,
    "limit": MAX_LIMIT,
})

# Кеш для проверки подписок (user_id: status)
subscription_cache = {}

# Загрузка данных
def load_user_data():
    global user_data
    if os.path.exists("user_data.json"):
        try:
            with open("user_data.json", "r", encoding="utf-8") as file:
                loaded_data = json.load(file)
                # Миграция старых данных
                for user_id, data in loaded_data.items():
                    if "limit" not in data:
                        data["limit"] = MAX_LIMIT
                user_data = defaultdict(lambda: {
                    "requests_used": 0,
                    "last_request_date": None,
                    "limit": MAX_LIMIT,
                }, loaded_data)
        except Exception as e:
            logger.error(f"Ошибка загрузки user_data: {e}")

# Сохранение данных
def save_user_data():
    try:
        with open("user_data.json", "w", encoding="utf-8") as file:
            json.dump(dict(user_data), file, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения user_data: {e}")

# История диалогов
def save_chat_history(user_id, history):
    try:
        file_name = f"user_chats/{user_id}.json"
        with open(file_name, "w", encoding="utf-8") as file:
            json.dump(history, file, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения истории для {user_id}: {e}")

def load_chat_history(user_id):
    file_name = f"user_chats/{user_id}.json"
    if os.path.exists(file_name):
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as e:
            logger.error(f"Ошибка загрузки истории для {user_id}: {e}")
    return []

# Инициализация данных
load_user_data()

# Очистка кеша подписок
def clear_subscription_cache(context: CallbackContext):
    global subscription_cache
    subscription_cache.clear()
    logger.info("Кеш подписок очищен")

# Управление лимитами
def update_limits(user_id):
    user = user_data[user_id]
    now = datetime.now()
    
    if user["last_request_date"]:
        last_update = datetime.fromisoformat(user["last_request_date"])
        if (now - last_update).days >= 1:
            user["limit"] = min(user["limit"] + DAILY_INCREMENT, MAX_LIMIT)
            user["last_request_date"] = now.isoformat()
    else:
        user["last_request_date"] = now.isoformat()
        user["limit"] = MAX_LIMIT

    return user["limit"]

def decrement_limit(user_id):
    if user_id in user_data:
        user_data[user_id]["limit"] = max(0, user_data[user_id]["limit"] - 1)

# Клавиатура
def create_subscribe_keyboard():
    keyboard = [
        [InlineKeyboardButton("Подписаться на группу", url=GROUP_INVITE_LINK)],
        [InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")],
    ]
    return InlineKeyboardMarkup(keyboard)

# Проверка подписки с кешированием
async def check_subscription(user_id, context: CallbackContext):
    if user_id in subscription_cache:
        return subscription_cache[user_id]
    
    try:
        chat_member = await context.bot.get_chat_member(GROUP_ID, user_id)
        is_subscribed = chat_member.status in ["member", "administrator", "creator"]
        subscription_cache[user_id] = is_subscribed
        return is_subscribed
    except Exception as e:
        logger.error(f"Ошибка проверки подписки {user_id}: {e}")
        return False

# Психолог-бот
system_prompt = """
Привет! Меня зовут Доктор Психея, и я — профессиональный психолог. 
Моя цель — помочь вам найти гармонию, справиться с трудностями и лучше понять себя. 
Здесь вы можете задать вопросы или просто поделиться тем, что вас беспокоит."""

def chat_with_psychologist(prompt, history=None):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    
    messages = [{"role": "system", "content": system_prompt}]
    
    if history:
        messages.extend(history)
    
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000,
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        logger.warning("Тайм-аут при запросе к DeepSeek API")
        return "Извините, сервер не отвечает. Пожалуйста, попробуйте позже."
    except Exception as e:
        logger.error(f"Ошибка DeepSeek API: {e}")
        return "Извините, произошла ошибка при обработке вашего запроса."

# Команда /start
async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    remaining = update_limits(user_id)
    
    await update.message.reply_text(
        f"Привет! Я — Доктор Психея, ваш виртуальный психолог.\n"
        f"У вас осталось {remaining} запросов.\n"
        f"Лимит пополняется на {DAILY_INCREMENT} запроса каждый день.\n"
        f"Подпишитесь на группу, чтобы получить безлимитный доступ: {GROUP_INVITE_LINK}",
        reply_markup=create_subscribe_keyboard()
    )

# Обработчик сообщений
async def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_message = update.message.text
    
    logger.info(f"Сообщение от {user_id}: {user_message[:50]}...")
    
    # Инициализация истории
    if "history" not in context.user_data:
        context.user_data["history"] = load_chat_history(user_id)
    
    # Проверка подписки
    is_subscribed = await check_subscription(user_id, context)
    
    # Проверка лимитов для неподписанных
    if not is_subscribed:
        remaining = update_limits(user_id)
        
        if remaining <= 0:
            await update.message.reply_text(
                "❌ У вас закончились запросы. Подпишитесь на группу для безлимитного доступа.",
                reply_markup=create_subscribe_keyboard()
            )
            return
        
        decrement_limit(user_id)
    
    # Генерация ответа
    try:
        bot_response = chat_with_psychologist(user_message, context.user_data["history"])
        logger.info(f"Ответ для {user_id}: {bot_response[:50]}...")
    except Exception as e:
        logger.error(f"Ошибка генерации ответа: {e}")
        bot_response = "⚠️ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."
    
    # Сохранение истории
    context.user_data["history"].append({"role": "user", "content": user_message})
    context.user_data["history"].append({"role": "assistant", "content": bot_response})
    save_chat_history(user_id, context.user_data["history"])
    
    # Формирование ответа
    response_text = bot_response
    if not is_subscribed:
        remaining = user_data[user_id]["limit"]
        response_text += f"\n\n🔢 Осталось запросов: {remaining}"
    
    # Отправка ответа
    await update.message.reply_text(
        response_text,
        reply_markup=create_subscribe_keyboard() if not is_subscribed else None
    )

# Обработчик кнопок
async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_subscription":
        user_id = query.from_user.id
        is_subscribed = await check_subscription(user_id, context)
        
        if is_subscribed:
            await query.edit_message_text("✅ Вы подписаны! Теперь у вас безлимитный доступ.")
        else:
            await query.edit_message_text(
                "❌ Вы не подписаны. Пожалуйста, подпишитесь для доступа:",
                reply_markup=create_subscribe_keyboard()
            )

# Основная функция
def main():
    # Создание приложения
    application = Application.builder().token(TOKEN).build()
    
    # Планировщик для очистки кеша
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            clear_subscription_cache, 
            interval=3600,  # Каждый час
            first=10
        )
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск бота
    logger.info("Бот запущен")
    application.run_polling(
        poll_interval=5.0,  # Оптимизированный интервал опроса
        close_loop=False,
        stop_signals=None
    )

# Точка входа
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        save_user_data()  # Сохраняем данные перед выходом
        raise
    finally:
        save_user_data()  # Гарантированное сохранение при завершении
