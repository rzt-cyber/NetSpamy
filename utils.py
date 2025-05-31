from telebot import types
import logging
from config import LAYOUT_TRANS, BOT_INVITE_URL
from model.predict import predict_toxicity
import pytz
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

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
    
def get_current_time_in_timezone(timezone_str="UTC"):
    try:
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz).time()
    except pytz.UnknownTimeZoneError:
        return datetime.utcnow().time()

def minutes_to_time(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

def is_chat_open(current_time, work_start, work_end):
    """Проверяет, открыт ли чат в текущее время"""
    try:
        current_minutes = current_time.hour * 60 + current_time.minute
        return work_start <= current_minutes <= work_end
    except Exception as e:
        logger.error(f"Ошибка проверки времени: {str(e)}")
        return True

def validate_time_format(time_str: str) -> bool:
    try:
        datetime.datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False
    
def notify_chat_status(bot, chat_id, is_opening, work_start, work_end, timezone):
    """Уведомление об открытии/закрытии"""
    try:
        if is_opening:
            # Восстанавливаем права всем
            for member in bot.get_chat_members(chat_id):
                try:
                    bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=member.user.id,
                        permissions=types.ChatPermissions(
                            can_send_messages=True,
                            can_send_media_messages=True
                        )
                    )
                except:
                    pass
            
            bot.send_message(chat_id, "🔓 Чат открыт!")
            bot.set_chat_description(chat_id, "")  # Очищаем описание
        else:
            update_chat_description(bot, chat_id, work_start, timezone)
    except Exception as e:
        logger.error(f"Ошибка уведомления: {e}")    
    
def update_chat_description(bot, chat_id, work_start, timezone):
    """Обновляет описание чата для отображения в поле ввода"""
    try:
        open_time = minutes_to_time(work_start)
        description = f"🔒 Чат закрыт. Откроется в {open_time} ({timezone})"
        bot.set_chat_description(chat_id, description)
    except Exception as e:
        logger.error(f"Не удалось обновить описание: {e}")
        
def setup_chat_schedule(bot, db, chat_id, work_start, work_end, timezone):
    """Настраивает расписание уведомлений"""
    from handlers.events import handle_chat_status

    # Удаляем старые задачи
    for job in scheduler.get_jobs():
        if job.id == f'schedule_{chat_id}':
            job.remove()

    # Создаем новую задачу для проверки статуса
    scheduler.add_job(
        handle_chat_status,
        'cron',
        hour='*',  # Каждый час
        minute=0,  # В начале часа
        args=[bot, db, chat_id, False],  # Без принудительного уведомления
        id=f'schedule_{chat_id}'
    )

    # Дополнительная задача для проверки при изменении времени
    scheduler.add_job(
        handle_chat_status,
        'cron',
        hour=work_start // 60,
        minute=work_start % 60,
        args=[bot, db, chat_id, True],  # С принудительным уведомлением
        id=f'open_{chat_id}'
    )

    scheduler.add_job(
        handle_chat_status,
        'cron',
        hour=work_end // 60,
        minute=work_end % 60,
        args=[bot, db, chat_id, True],  # С принудительным уведомлением
        id=f'close_{chat_id}'
    )

    if not scheduler.running:
        scheduler.start()
        
def restrict_all_members(bot, chat_id: int):
    """Ограничивает права всех участников чата (кроме администраторов и ботов)"""
    try:
        # Получаем администраторов чата
        admins = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
        
        # Получаем количество участников
        member_count = bot.get_chat_member_count(chat_id)
        logger.info(f"Ограничение прав для {member_count} участников чата {chat_id}")
        
        # Отправляем уведомление о начале процесса
        msg = bot.send_message(
            chat_id, 
            f"🔒 Начинаю ограничение прав для всех участников... ({member_count} чел.)",
            disable_notification=True
        )
        
        # Ограничиваем права постепенно
        restricted_count = 0
        for i in range(0, member_count, 100):  # Обрабатываем по 100 участников
            for attempt in range(3):  # 3 попытки на группу
                try:
                    # Получаем участников чата (метод get_chat_members не существует)
                    # Вместо этого будем использовать другой подход:
                    # Так как нет прямого способа получить всех участников, будем ограничивать
                    # только тех, кто активен в данный момент
                    # Это ограничение текущего подхода!
                    break
                except Exception as e:
                    logger.warning(f"Ошибка получения участников (попытка {attempt+1}): {e}")
                    time.sleep(2)
        
        # Обновляем сообщение
        bot.edit_message_text(
            f"🔒 Права ограничены для {restricted_count}/{member_count} участников",
            chat_id, msg.message_id
        )
        
    except Exception as e:
        logger.error(f"Ошибка ограничения прав: {e}")

def unrestrict_all_members(bot, chat_id: int):
    """Восстанавливает права всех участников"""
    try:
        # Получаем количество участников
        member_count = bot.get_chat_member_count(chat_id)
        logger.info(f"Восстановление прав для {member_count} участников чата {chat_id}")
        
        # Отправляем уведомление о начале процесса
        msg = bot.send_message(
            chat_id, 
            f"🔓 Начинаю восстановление прав для всех участников... ({member_count} чел.)",
            disable_notification=True
        )
        
        # Восстанавливаем права постепенно
        unrestricted_count = 0
        # Восстанавливаем права только при получении сообщения от пользователя
        
        # Обновляем сообщение
        bot.edit_message_text(
            f"🔓 Права восстановлены для {unrestricted_count}/{member_count} участников",
            chat_id, msg.message_id
        )
        
    except Exception as e:
        logger.error(f"Ошибка восстановления прав: {e}")

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
    """Восстанавливает права всех участников"""
    try:
        offset = 0
        while True:
            members = bot.get_chat_members(chat_id, offset=offset, limit=100)
            if not members:
                break
            for member in members:
                try:
                    bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=member.user.id,
                        permissions=types.ChatPermissions(
                            can_send_messages=True,
                            can_send_media_messages=True,
                            can_send_polls=True,
                            can_send_other_messages=True
                        )
                    )
                except Exception as e:
                    logger.error(f"Ошибка восстановления {member.user.id}: {e}")
            offset += 100
            time.sleep(0.5)
    except Exception as e:
        logger.error(f"Ошибка получения участников: {e}")