from telebot import types
import logging
from config import BOT_INVITE_URL, MESSAGE_LIFETIME_SECONDS
from model.predict import predict_toxicity
from threading import Timer

logger = logging.getLogger(__name__)

def delete_message_after_delay(bot, chat_id, message_id, db):
    """Удаляет сообщение через заданное время, если чат не является группой для репортов."""
    try:
        db.cursor.execute("SELECT chat_id FROM report_chats WHERE log_chat_id = ?", (chat_id,))
        if db.cursor.fetchone():
            logger.info(f"Сообщение {message_id} в чате {chat_id} не удаляется, так как это группа для репортов")
            return
        def delete():
            try:
                bot.delete_message(chat_id, message_id)
                logger.info(f"Сообщение {message_id} удалено в чате {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка удаления сообщения {message_id} в чате {chat_id}: {e}")
        Timer(MESSAGE_LIFETIME_SECONDS, delete).start()
    except Exception as e:
        logger.error(f"Ошибка в планировании удаления сообщения {message_id} в чате {chat_id}: {e}")

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

def unrestrict_user(bot, chat_id: int, user_id: int):
    """Восстанавливает права конкретному пользователю"""
    try:
        bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            )
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка восстановления прав для {user_id}: {e}")
        return False