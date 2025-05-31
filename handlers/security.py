import logging
from telebot import types

logger = logging.getLogger(__name__)

# Список опасных расширений файлов
DANGEROUS_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.dll', '.js', '.vbs', 
    '.ps1', '.sh', '.jar', '.msi', '.scr', '.reg',
    '.com', '.pif', '.application', '.gadget', '.msc',
    '.msp', '.hta', '.cpl', '.msh', '.msh1', '.msh2',
    '.mshxml', '.msh1xml', '.msh2xml', '.scf', '.lnk',
    '.inf', '.docm', '.dotm', '.xlsm', '.xltm', '.xlam',
    '.pptm', '.potm', '.ppam', '.ppsm', '.sct', '.wsf'
}

def is_dangerous_file(message: types.Message) -> bool:
    """Проверяет, является ли файл потенциально опасным"""
    if message.document:
        file_name = message.document.file_name or ""
        file_ext = file_name[file_name.rfind('.'):].lower()
        return file_ext in DANGEROUS_EXTENSIONS
    return False

def handle_dangerous_file(bot, message: types.Message, db):
    """Обрабатывает опасные файлы - удаляет и наказывает отправителя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        bot.delete_message(chat_id, message.message_id)
        
        warnings = db.add_warning(chat_id, user_id)
        
        warning_msg = bot.send_message(
            chat_id,
            f"⚠️ {message.from_user.first_name} отправил запрещенный файл. "
            f"Предупреждение {warnings}/3"
        )
        
        if warnings >= 3:
            if db.get_mute(chat_id, user_id):
                return
                
            bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
            if bot_member.can_restrict_members:
                from datetime import datetime, timedelta
                unmute_time = datetime.now() + timedelta(hours=24)
                db.add_mute(chat_id, user_id, unmute_time)
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "Размьютить",
                    callback_data=f"unmute_{chat_id}_{user_id}"
                ))
                
                bot.send_message(
                    chat_id,
                    f"🚫 {message.from_user.first_name} получил 3 предупреждения "
                    f"и замьючен на 24 часа за отправку опасных файлов.",
                    reply_markup=markup
                )
    except Exception as e:
        logger.error(f"Ошибка при обработке опасного файла: {e}")