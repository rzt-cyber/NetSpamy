from telebot import types
import re
import logging
import sqlite3
from .security import is_dangerous_file, handle_dangerous_file
from datetime import datetime, timedelta
from config import PROFANITY_REGEX, MESSAGE_LIFETIME_SECONDS, LINK_REGEX
from utils import get_username, create_main_menu, unrestrict_user, check_message, delete_message_after_delay
from database import Database
from .callbacks import create_admin_menu, create_settings_menu, waiting_for_rules

logger = logging.getLogger(__name__)


def register_events(bot, db: Database):
    """Регистрация обработчиков событий"""
    
    global _bot, _db
    _bot = bot
    _db = db
    
    @bot.my_chat_member_handler()
    def handle_chat_member_update(update):
        try:
            logger.info(f"Получено обновление my_chat_member: {update}")
            chat_id = update.chat.id

            if update.new_chat_member.status == 'kicked' and update.chat.type in ['group', 'supergroup']:
                logger.info(f"Бот удален из группы {chat_id}")
                with sqlite3.connect(db.db_name) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
                    cursor.execute("DELETE FROM admins WHERE chat_id = ?", (chat_id,))
                    cursor.execute("DELETE FROM warnings WHERE chat_id = ?", (chat_id,))
                    cursor.execute("DELETE FROM reports WHERE chat_id = ?", (chat_id,))
                    cursor.execute("DELETE FROM chat_members WHERE chat_id = ?", (chat_id,))
                    cursor.execute("DELETE FROM report_chats WHERE chat_id = ? OR log_chat_id = ?", (chat_id, chat_id))
                    cursor.execute("DELETE FROM captcha_status WHERE chat_id = ?", (chat_id,))
                    conn.commit()
                    logger.info(f"Данные группы {chat_id} удалены из базы")
                return

            if (update.old_chat_member.status == 'kicked' and 
                update.new_chat_member.status in ['member', 'administrator'] and 
                update.chat.type in ['group', 'supergroup']):
                logger.info(f"Бот добавлен в группу {chat_id}")
                db.add_group(chat_id)
                try:
                    admins = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
                    db.update_admins(chat_id, admins)
                    db.mark_existing_members(chat_id, bot)
                    logger.info(f"Администраторы группы {chat_id} обновлены: {admins}")
                except Exception as e:
                    logger.error(f"Ошибка обновления админов группы {chat_id}: {e}")

                # Проверка прав бота
                bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
                if not (bot_member.can_delete_messages and bot_member.can_restrict_members):
                    sent_message = bot.send_message(
                        chat_id,
                        "⚠️ У меня недостаточно прав для управления чатом! "
                        "Пожалуйста, дайте мне права администратора с возможностью удалять сообщения и ограничивать участников."
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    return

                settings = db.get_group_settings(chat_id)
                if settings.get('greeting_enabled', True):
                    sent_message = bot.send_message(
                        chat_id,
                        "✅ Бот успешно добавлен в группу! "
                        "Для настройки перейдите в личные сообщения бота и используйте команду /start."
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    logger.info(f"Приветственное сообщение отправлено в группу {chat_id}")

                for admin_id in db.get_admins(chat_id):
                    try:
                        admin = bot.get_chat_member(chat_id, admin_id).user
                        if admin.is_bot:
                            logger.info(f"Пропущен админ {admin_id}, так как это бот")
                            continue
                        existing_message_id = db.get_welcome_message(admin_id)
                        if existing_message_id:
                            try:
                                bot.edit_message_text(
                                    f"Бот добавлен в группу {update.chat.title}. Выберите группу для управления:",
                                    admin_id,
                                    existing_message_id,
                                    reply_markup=create_admin_menu(bot, admin_id, db)
                                )
                                logger.info(f"Обновлено приветственное сообщение для {admin_id}: message_id {existing_message_id}")
                            except Exception as e:
                                logger.error(f"Ошибка обновления сообщения для {admin_id}: {e}")
                                sent_message = bot.send_message(
                                    admin_id,
                                    f"Бот добавлен в группу {update.chat.title}. Выберите группу для управления:",
                                    reply_markup=create_admin_menu(bot, admin_id, db)
                                )
                                db.save_welcome_message(admin_id, sent_message.message_id)
                                logger.info(f"Новое приветственное сообщение отправлено для {admin_id}: message_id {sent_message.message_id}")
                        else:
                            sent_message = bot.send_message(
                                admin_id,
                                f"Бот добавлен в группу {update.chat.title}. Выберите группу для управления:",
                                reply_markup=create_admin_menu(bot, admin_id, db)
                            )
                            db.save_welcome_message(admin_id, sent_message.message_id)
                            logger.info(f"Новое приветственное сообщение отправлено для {admin_id}: message_id {sent_message.message_id}")
                    except Exception as e:
                        logger.error(f"Ошибка уведомления админа {admin_id}: {e}")

        except Exception as e:
            logger.error(f"Ошибка в handle_chat_member_update: {e}")

    @bot.message_handler(content_types=['new_chat_members'])
    def handle_new_chat_members(message):
        """Обработка новых участников"""
        try:
            chat_id = message.chat.id
            db.cursor.execute("SELECT chat_id FROM report_chats WHERE log_chat_id = ?", (chat_id,))
            if db.cursor.fetchone():
                logger.info(f"Событие new_chat_members в чате {chat_id} пропущено, так как это группа для репортов")
                return

            try:
                bot.delete_message(chat_id, message.message_id)
                logger.info(f"Системное сообщение {message.message_id} удалено в чате {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка удаления системного сообщения {message.message_id} в чате {chat_id}: {e}")

            settings = db.get_group_settings(chat_id)
            if not settings.get('greeting_enabled', True):
                return

            for member in message.new_chat_members:
                user_id = member.id
                username = member.username or member.first_name
                logger.info(f"Новый участник {user_id} ({username}) в группе {chat_id}")
                db.add_chat_member(chat_id, user_id)

                if settings.get('captcha_enabled', True):
                    try:
                        bot.restrict_chat_member(
                            chat_id,
                            user_id,
                            permissions=types.ChatPermissions(can_send_messages=False)
                        )
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton(
                            "Пройти капчу",
                            callback_data=f"captcha_{chat_id}_{user_id}"
                        ))
                        sent_message = bot.send_message(
                            chat_id,
                            f"Добро пожаловать, {get_username(bot, chat_id, user_id)}! "
                            f"Пройдите капчу, нажав на кнопку ниже, чтобы начать писать в чат.\n"
                            f"Ознакомьтесь с правилами и командами через /info.",
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    except Exception as e:
                        logger.error(f"Ошибка при установке ограничений для {user_id} в чате {chat_id}: {e}")
                else:
                    sent_message = bot.send_message(
                        chat_id,
                        f"Добро пожаловать, {get_username(bot, chat_id, user_id)}! "
                        f"Ознакомьтесь с правилами и командами через /info.",
                        parse_mode='HTML'
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)

        except Exception as e:
            logger.error(f"Ошибка в handle_new_chat_members: {e}")

    @bot.message_handler(content_types=['left_chat_member'])
    def handle_left_chat_member(message):
        """Обработка выхода участников"""
        try:
            chat_id = message.chat.id
            db.cursor.execute("SELECT chat_id FROM report_chats WHERE log_chat_id = ?", (chat_id,))
            if db.cursor.fetchone():
                logger.info(f"Событие left_chat_member в чате {chat_id} пропущено, так как это группа для репортов")
                return

            settings = db.get_group_settings(chat_id)
            if not settings.get('greeting_enabled', True):
                return

            user_id = message.left_chat_member.id
            logger.info(f"Участник {user_id} покинул группу {chat_id}")
            db.remove_chat_member(chat_id, user_id)

            try:
                bot.delete_message(chat_id, message.message_id)
                logger.info(f"Системное сообщение {message.message_id} удалено в чате {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка удаления системного сообщения {message.message_id} в чате {chat_id}: {e}")

            sent_message = bot.send_message(
                chat_id,
                f"Пользователь {get_username(bot, chat_id, user_id)} покинул группу.",
                parse_mode='HTML'
            )
            delete_message_after_delay(bot, chat_id, sent_message.message_id, db)

        except Exception as e:
            logger.error(f"Ошибка в handle_left_chat_member: {e}")

    @bot.message_handler(content_types=['text'])
    def handle_text_messages(message):
        """Обработка текстовых сообщений"""
        try:
            user_id = message.from_user.id
            chat_id = message.chat.id

            # Проверка, является ли пользователь администратором
            admins = db.get_admins(chat_id)
            if user_id in admins:
                logger.info(f"Сообщение от администратора {user_id} в группе {chat_id} пропущено")
                return

            if user_id in waiting_for_rules:
                wait_data = waiting_for_rules.get(user_id)
                group_id = wait_data['group_id']
                db.update_info_rules(group_id, message.text)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("← Назад", callback_data=f"settings_{group_id}"))
                bot.edit_message_text(
                    f"📜 Новые правила установлены:\n\n{message.text}",
                    wait_data['chat_id'],
                    wait_data['message_id'],
                    reply_markup=markup
                )
                bot.delete_message(chat_id=user_id, message_id=message.message_id) 
                del waiting_for_rules[user_id]
                logger.info(f"Новые правила установлены для группы {group_id} пользователем {user_id}")
                return

            if message.chat.type not in ['group', 'supergroup']:
                return

            settings = db.get_group_settings(chat_id)

            # Проверка капчи
            if settings.get('captcha_enabled', True) and not db.has_passed_captcha(chat_id, user_id):
                bot.delete_message(chat_id, message.message_id)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "Пройти капчу",
                    callback_data=f"captcha_{chat_id}_{user_id}"
                ))
                sent_message = bot.send_message(
                    chat_id,
                    f"{get_username(bot, chat_id, user_id)}, пройдите капчу, чтобы отправлять сообщения!",
                    parse_mode='HTML',
                    reply_markup=markup
                )
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                logger.info(f"Сообщение от {user_id} удалено в группе {chat_id}, так как капча не пройдена")
                return

            # Проверка фильтров в порядке приоритета
            if settings.get('profanity_filter', True):
                if re.search(PROFANITY_REGEX, message.text.lower()):
                    warning_count = db.add_warning(chat_id, user_id)
                    bot.delete_message(chat_id, message.message_id)
                    sent_message = bot.send_message(
                        chat_id,
                        f"{get_username(bot, chat_id, user_id)}, не используйте нецензурные выражения! Предупреждение {warning_count}/3.",
                        parse_mode='HTML'
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    logger.info(f"Обнаружен мат в сообщении от {user_id} в группе {chat_id}, предупреждение {warning_count}")

                    if warning_count >= 3:
                        unmute_time = datetime.now() + timedelta(hours=1)
                        bot.restrict_chat_member(
                            chat_id,
                            user_id,
                            until_date=unmute_time,
                            permissions=types.ChatPermissions(can_send_messages=False)
                        )
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton(
                            "Размьютить",
                            callback_data=f"unmute_{chat_id}_{user_id}"
                        ))
                        sent_message = bot.send_message(
                            chat_id,
                            f"Пользователь {get_username(bot, chat_id, user_id)} замьючен на 1 час за 3 предупреждения.",
                            reply_markup=markup,
                            parse_mode='HTML'
                        )
                        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                        db.reset_warnings(chat_id, user_id)
                        logger.info(f"Пользователь {user_id} замьючен в группе {chat_id} за 3 предупреждения")
                    return  # Прекращаем дальнейшие проверки

            if settings.get('link_filter', True):
                if re.search(LINK_REGEX, message.text):
                    warning_count = db.add_warning(chat_id, user_id)
                    bot.delete_message(chat_id, message.message_id)
                    sent_message = bot.send_message(
                        chat_id,
                        f"{get_username(bot, chat_id, user_id)}, отправка ссылок запрещена! Предупреждение {warning_count}/3.",
                        parse_mode='HTML'
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    logger.info(f"Обнаружена ссылка в сообщении от {user_id} в группе {chat_id}, предупреждение {warning_count}")

                    if warning_count >= 3:
                        unmute_time = datetime.now() + timedelta(hours=1)
                        bot.restrict_chat_member(
                            chat_id,
                            user_id,
                            until_date=unmute_time,
                            permissions=types.ChatPermissions(can_send_messages=False)
                        )
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton(
                            "Размьютить",
                            callback_data=f"unmute_{chat_id}_{user_id}"
                        ))
                        sent_message = bot.send_message(
                            chat_id,
                            f"Пользователь {get_username(bot, chat_id, user_id)} замьючен на 1 час за 3 предупреждения.",
                            reply_markup=markup,
                            parse_mode='HTML'
                        )
                        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                        db.reset_warnings(chat_id, user_id)
                        logger.info(f"Пользователь {user_id} замьючен в группе {chat_id} за 3 предупреждения")
                    return  # Прекращаем дальнейшие проверки

            if settings.get('toxicity_filter', True):
                toxicity_result = check_message(message.text)
                if toxicity_result['is_toxic']:
                    warning_count = db.add_warning(chat_id, user_id)
                    bot.delete_message(chat_id, message.message_id)
                    sent_message = bot.send_message(
                        chat_id,
                        f"{get_username(bot, chat_id, user_id)}, ваше сообщение слишком токсично! Предупреждение {warning_count}/3.",
                        parse_mode='HTML'
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    logger.info(f"Обнаружено токсичное сообщение от {user_id} в группе {chat_id}, предупреждение {warning_count}")

                    if warning_count >= 3:
                        unmute_time = datetime.now() + timedelta(hours=1)
                        bot.restrict_chat_member(
                            chat_id,
                            user_id,
                            until_date=unmute_time,
                            permissions=types.ChatPermissions(can_send_messages=False)
                        )
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton(
                            "Размьютить",
                            callback_data=f"unmute_{chat_id}_{user_id}"
                        ))
                        sent_message = bot.send_message(
                            chat_id,
                            f"Пользователь {get_username(bot, chat_id, user_id)} замьючен на 1 час за 3 предупреждения.",
                            reply_markup=markup,
                            parse_mode='HTML'
                        )
                        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                        db.reset_warnings(chat_id, user_id)
                        logger.info(f"Пользователь {user_id} замьючен в группе {chat_id} за 3 предупреждения")
                    return  # Если обнаружено нарушение, прекращаем дальнейшие проверки

        except Exception as e:
            logger.error(f"Ошибка в handle_text_messages: {e}")

    @bot.message_handler(content_types=['document', 'photo', 'audio', 'voice'])
    def handle_files(message):
        """Обработка файлов"""
        try:
            if message.chat.type not in ['group', 'supergroup']:
                return

            chat_id = message.chat.id
            user_id = message.from_user.id
            admins = db.get_admins(chat_id)
            if user_id in admins:
                logger.info(f"Файл от администратора {user_id} в группе {chat_id} пропущен")
                return

            settings = db.get_group_settings(chat_id)

            # Проверка капчи для файлов
            if settings.get('captcha_enabled', True) and not db.has_passed_captcha(chat_id, user_id):
                bot.delete_message(chat_id, message.message_id)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    text="Пройти капчу",
                    callback_data=f"captcha_{chat_id}_{user_id}"
                ))
                sent_message = bot.send_message(
                    chat_id,
                    f"{get_username(bot, chat_id, user_id)}, пройдите капчу, чтобы отправлять файлы!",
                    parse_mode='HTML',
                    reply_markup=markup
                )
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                logger.info(f"Файл от {user_id} удален в группе {chat_id}, так как капча не пройдена")
                return

            if settings.get('file_filter', True):
                if is_dangerous_file(message):
                    handle_dangerous_file(bot, db, chat_id, user_id, message.message_id)
                    logger.info(f"Обнаружен опасный файл от {user_id} в группе {chat_id}")

        except Exception as e:
            logger.error(f"Ошибка в handle_files: {e}")