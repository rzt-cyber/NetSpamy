from telebot import types
import logging
from config import LAYOUT_TRANS, BOT_INVITE_URL
from model.predict import predict_toxicity
import pytz
from datetime import datetime

logger = logging.getLogger(__name__)

def is_latin_text(text):
    """Проверяет, содержит ли текст только латинские символы (ошибка раскладки)"""
    if not all(ord(char) < 128 for char in text):
        return False
    if len(text) <= 3:
        return False
    if ' ' in text or text.isalpha() and len(text.split()) > 1:
        return False
    return True

def correct_layout(text):
    """Корректирует раскладку с латинской на русскую"""
    return text.translate(LAYOUT_TRANS)

def get_username(bot, chat_id, user_id):
    """Возвращает username или упоминание пользователя"""
    try:
        user = bot.get_chat_member(chat_id, user_id).user
        if user.username:
            return f"@{user.username}"
        return f'<a href="tg://user?id={user_id}">{user.first_name}</a>'
    except Exception as e:
        logger.error(f"Ошибка получения имени пользователя {user_id}: {e}")
        return f"user_id {user_id}"

def parse_mute_duration(duration_str):
    """Парсит длительность мута (например, 1h, 30m, 2d)"""
    if not duration_str:
        return 24 * 60 * 60
    try:
        unit = duration_str[-1].lower()
        value = int(duration_str[:-1])
        if unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 60 * 60
        elif unit == 'd':
            return value * 24 * 60 * 60
        return 24 * 60 * 60
    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка парсинга длительности мута: {e}")
        return 24 * 60 * 60

def format_duration(seconds):
    """Форматирует длительность в читаемый вид"""
    if seconds < 60:
        return f"{seconds} секунд"
    elif seconds < 3600:
        return f"{seconds // 60} минут"
    elif seconds < 86400:
        return f"{seconds // 3600} часов"
    return f"{seconds // 86400} дней"

def create_main_menu():
    """Создает главное меню с кнопкой добавления бота"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "Добавить бота в группу",
        url=BOT_INVITE_URL
    ))
    return markup

def check_message(text):
    """Проверяет сообщение на токсичность."""
    try:
        result = predict_toxicity(text)
        logger.info(f"Проверка токсичности текста '{text}': is_toxic={result == 1}, label={result}")
        return {
            "is_toxic": result == 1,
            "label": result
        }
    except Exception as e:
        logger.error(f"Ошибка в predict_toxicity для текста '{text}': {e}") 
        return {"is_toxic": False, "label": 0}
    
def get_current_time_in_timezone(timezone):
    tz = pytz.timezone(timezone)
    return datetime.now(tz).time()

def minutes_to_time(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

def is_chat_open(current_time, work_start, work_end):
    current_minutes = current_time.hour * 60 + current_time.minute
    return work_start <= current_minutes < work_end

    