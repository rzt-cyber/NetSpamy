import logging
from telebot import types
from utils import get_username, delete_message_after_delay

logger = logging.getLogger(__name__)

DANGEROUS_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.dll', '.js', '.vbs',
    '.ps1', '.sh', '.jar', '.msi', '.scr', '.reg',
    '.com', '.pif', '.application', '.gadget', '.msc',
    '.msp', '.hta', '.cpl', '.msh', '.msh1', '.msh2',
    '.mshxml', '.msh1xml', '.msh2xml', '.scff', '.lnk',
    '.inf', '.docm', '.dotm', '.xlsm', '.xltm', '.xlam',
    '.pptm', '.potm', '.ppam', '.ppsm', '.sct', '.wsf',
    '.py', '.pyc', '.pyo', '.vb', '.rbb', '.rb', '.php', '.asp', '.aspx'
}

# Разрешённые расширения для медиафайлов
ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp',  # Изображения
    '.mp4', '.mov', '.avi', '.mkv',  # Видео
    '.mp3', '.wav', '.ogg',  # Аудио
    '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'  # Документы
}

def is_dangerous_file(message: types.Message) -> bool:
    """Проверяет, является ли файл в сообщении потенциально опасным"""
    try:
        file_info = None
        if message.document:
            file_info = message.document
        elif message.audio:
            file_info = message.audio
        elif message.video:
            file_info = message.video
        elif message.voice:
            file_info = message.voice

        if not file_info:
            logger.warning(f"Нет файла в сообщении {message.message_id}")
            return False

        file_name = file_info.file_name or ""
        file_ext = file_name[file_name.rfind('.'):].lower() if '.' in file_name else ""

        if not file_ext:
            logger.warning(f"Файл в сообщении {message.message_id} не имеет расширения")
            return True  # Если расширение отсутствует, считаем файл подозрительным

        if file_ext in DANGEROUS_EXTENSIONS:
            logger.info(f"Обнаружен опасный файл с расширением {file_ext} в сообщении {message.message_id}")
            return True
        if file_ext not in ALLOWED_EXTENSIONS:
            logger.info(f"Файл с неизвестным расширением {file_ext} в сообщении {message.message_id}")
            return True  # Неизвестные расширения считаем опасными
        logger.info(f"Файл с расширением {file_ext} в сообщении {message.message_id} разрешён")
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки файла в сообщении {message.message_id}: {e}")
        return True  # В случае ошибки считаем файл опасным

def handle_dangerous_file(bot, db, chat_id, user_id, message_id):
    """Обрабатывает опасные файлы - удаляет и банит отправителя"""
    try:
        # Удаляем сообщение с опасным файлом
        bot.delete_message(chat_id, message_id)
        
        # Проверяем права бота
        bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
        if bot_member.can_restrict_members:
            bot.kick_chat_member(chat_id, user_id)
            sent_message = bot.send_message(
                chat_id,
                f"🚫 {get_username(bot, chat_id, user_id)} забанен за отправку опасного файла.",
                parse_mode='HTML'
            )
            logger.info(f"Пользователь {user_id} забанен за отправку опасного файла в чате {chat_id}")
            # Сбрасываем предупреждения, если они были
            db.reset_warnings(chat_id, user_id)
            # Планируем удаление сообщения о бане
            delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
        else:
            sent_message = bot.send_message(
                chat_id,
                f"⚠️ {get_username(bot, chat_id, user_id)} отправил запрещённый файл, но у бота недостаточно прав для бана.",
                parse_mode='HTML'
            )
            logger.warning(f"Недостаточно прав для бана пользователя {user_id} в чате {chat_id}")
            delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
    except Exception as e:
        logger.error(f"Ошибка при обработке опасного файла для пользователя {user_id} в чате {chat_id}: {e}")
        sent_message = bot.send_message(
            chat_id,
            f"❌ Произошла ошибка при обработке опасного файла от {get_username(bot, chat_id, user_id)}.",
            parse_mode='HTML'
        )
        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)