import os
import json
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")


# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаем папку для хранения истории, если её нет
if not os.path.exists("user_chats"):
    os.makedirs("user_chats")

# Пригласительная ссылка на группу
GROUP_INVITE_LINK = "https://t.me/+zoLEVViEZ7RkMzIy"

# ID группы (можно получить через бота @username_to_id_bot)
GROUP_ID = "-1002331837814"  # Замените на реальный ID вашей группы

# Структура для хранения данных пользователей
user_data = defaultdict(lambda: {
    "requests_used": 0,  # Количество использованных запросов
    "last_request_date": None,  # Дата последнего запроса
    "limit": 6,  # Максимальный лимит запросов
})

# Лимиты для всех пользователей
DAILY_INCREMENT = 2  # 2 запроса в день
MAX_LIMIT = 6  # Максимальный лимит запросов

# Функция для сохранения данных пользователей
def save_user_data():
    with open("user_data.json", "w", encoding="utf-8") as file:
        json.dump(dict(user_data), file, ensure_ascii=False, indent=4)

# Функция для загрузки данных пользователей
def load_user_data():
    global user_data
    if os.path.exists("user_data.json"):
        with open("user_data.json", "r", encoding="utf-8") as file:
            user_data = defaultdict(lambda: {
                "requests_used": 0,
                "last_request_date": None,
                "limit": MAX_LIMIT,
            }, json.load(file))

# Функция для сохранения истории диалогов
def save_chat_history(user_id, history):
    file_name = f"user_chats/{user_id}.json"
    with open(file_name, "w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=4)

# Функция для загрузки истории диалогов
def load_chat_history(user_id):
    file_name = f"user_chats/{user_id}.json"
    if os.path.exists(file_name):
        with open(file_name, "r", encoding="utf-8") as file:
            return json.load(file)
    return []

# Загружаем данные при старте
load_user_data()

# Сохраняем данные при завершении
import atexit
atexit.register(save_user_data)

# Функция для проверки и обновления лимитов
def update_limits(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            "requests_used": 0,
            "last_request_date": datetime.now().isoformat(),
            "limit": MAX_LIMIT,
        }

    user = user_data[user_id]
    now = datetime.now()
    last_update = datetime.fromisoformat(user["last_request_date"])

    # Если прошло больше суток, обновляем лимит
    if (now - last_update).days >= 1:
        user["limit"] = min(user["limit"] + DAILY_INCREMENT, MAX_LIMIT)
        user["last_request_date"] = now.isoformat()

    return user["limit"]

# Функция для уменьшения лимита
def decrement_limit(user_id):
    if user_id in user_data:
        user_data[user_id]["limit"] -= 1
        save_user_data()  # Сохраняем данные после изменения

# Функция для создания клавиатуры с кнопкой "Подписаться на группу"
def create_subscribe_keyboard():
    keyboard = [
        [InlineKeyboardButton("Подписаться на группу", url=GROUP_INVITE_LINK)],
        [InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")],
    ]
    return InlineKeyboardMarkup(keyboard)

# Функция для проверки подписки на группу
async def check_subscription(user_id, context: CallbackContext):
    try:
        chat_member = await context.bot.get_chat_member(GROUP_ID, user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        return False

# Системный промпт для бота-психолога
system_prompt = """


"Привет! Меня зовут [Твое имя], и я — профессиональный психолог. Моя цель — помочь вам найти гармонию, справиться с трудностями и лучше понять себя. Здесь вы можете записаться на консультацию, задать вопросы или просто поделиться тем, что вас беспокоит. 

Чтобы записаться на прием, выберите удобное время и дату из доступных слотов ниже. Если у вас есть вопросы или вы хотите обсудить что-то перед записью, напишите мне — я всегда готов вас поддержать. 😊"""

# Функция для общения с API DeepSeek
def chat_with_psychologist(prompt, history=None):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": "Bearer sk-976e6fd092044b488c96cf103b1ebab4",
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": "deepseek-chat",
        "messages": messages,
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        logger.error("Тайм-аут при запросе к API")
        return "Извините, сервер не отвечает. Пожалуйста, попробуйте позже."
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к API: {e}")
        return "Извините, произошла ошибка. Пожалуйста, попробуйте ещё раз."

# Команда /start
async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    update_limits(user_id)  # Обновляем лимиты
    await update.message.reply_text(
        f"Привет! Я — Доктор Психея, ваш виртуальный психолог.\n"
        f"У вас осталось {user_data[user_id]['limit']} запросов.\n"
        f"Лимит пополняется на {DAILY_INCREMENT} запроса каждый день.\n"
        f"Подпишитесь на группу, чтобы получить безлимитный доступ: {GROUP_INVITE_LINK}",
        reply_markup=create_subscribe_keyboard()
    )

# Обработка текстовых сообщений
async def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_message = update.message.text

    # Загружаем историю диалогов
    if "history" not in context.user_data:
        context.user_data["history"] = load_chat_history(user_id)

    # Проверяем подписку на группу
    is_subscribed = await check_subscription(user_id, context)

    # Если пользователь подписан, лимиты не применяются
    if is_subscribed:
        # Обработка сообщения
        logger.info(f"Пользователь: {user_message}")

        # Генерация ответа
        bot_response = chat_with_psychologist(user_message, context.user_data["history"])
        logger.info(f"Бот: {bot_response}")

        # Добавляем вопрос пользователя и ответ бота в историю
        context.user_data["history"].append({"role": "user", "content": user_message})
        context.user_data["history"].append({"role": "assistant", "content": bot_response})

        # Сохраняем историю
        save_chat_history(user_id, context.user_data["history"])

        # Отправляем ответ пользователю
        await update.message.reply_text(bot_response)
        return

    # Если пользователь не подписан, применяем лимиты
    remaining_requests = update_limits(user_id)

    # Проверяем лимиты
    if remaining_requests <= 0:
        await update.message.reply_text(
            "У вас закончились запросы. Подпишитесь на группу, чтобы получить безлимитный доступ.",
            reply_markup=create_subscribe_keyboard()
        )
        return

    # Уменьшаем лимит
    decrement_limit(user_id)

    # Обработка сообщения
    logger.info(f"Пользователь: {user_message}")

    # Генерация ответа
    bot_response = chat_with_psychologist(user_message, context.user_data["history"])
    logger.info(f"Бот: {bot_response}")

    # Добавляем вопрос пользователя и ответ бота в историю
    context.user_data["history"].append({"role": "user", "content": user_message})
    context.user_data["history"].append({"role": "assistant", "content": bot_response})

    # Сохраняем историю
    save_chat_history(user_id, context.user_data["history"])

    # Отправляем ответ пользователю
    await update.message.reply_text(
        f"{bot_response}\n\n"
        f"Осталось запросов: {user_data[user_id]['limit']}",
        reply_markup=create_subscribe_keyboard()
    )

# Обработка нажатий на кнопки
async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "check_subscription":
        user_id = query.from_user.id
        is_subscribed = await check_subscription(user_id, context)

        if is_subscribed:
            await query.edit_message_text(
                "Спасибо за подписку! Теперь у вас безлимитный доступ."
            )
        else:
            await query.edit_message_text(
                "Вы не подписаны на группу. Пожалуйста, подпишитесь, чтобы продолжить.",
                reply_markup=create_subscribe_keyboard()
            )

# Основная функция
def main():
    # Проверяем загрузку токена
    if not TOKEN:
        logger.error("Токен бота не найден! Проверьте .env файл.")
        exit(1)
    
    # Создаём приложение с корректным токеном
    application = Application.builder().token(TOKEN).build()

    # Регистрируем обработчики команд и сообщений
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Запускаем бота
    logger.info("Бот запущен")
    application.run_polling()

# Запуск скрипта
if __name__ == "__main__":
    main()
