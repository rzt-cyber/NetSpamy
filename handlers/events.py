from telebot import types
import re
import logging
import sqlite3
from datetime import datetime, timedelta
from config import PROFANITY_REGEX
from utils import is_latin_text, correct_layout, get_username, check_message
from database import Database
from handlers.callbacks import create_admin_menu

logger = logging.getLogger(__name__)

def register_events(bot, db: Database):
    """Регистрация обработчиков событий"""

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
                    cursor.execute("DELETE FROM mutes WHERE chat_id = ?", (chat_id,))
                    cursor.execute("DELETE FROM reports WHERE chat_id = ?", (chat_id,))
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
                    logger.info(f"Администраторы группы {chat_id} обновлены: {admins}")
                except Exception as e:
                    logger.error(f"Ошибка обновления админов группы {chat_id}: {e}")

                settings = db.get_group_settings(chat_id)
                if settings.get('greeting_enabled', True):
                    bot.send_message(
                        chat_id,
                        "Добро пожаловать в группу! Я бот-администратор. Используйте /help для списка команд."
                    )
                    logger.info(f"Приветственное сообщение отправлено в группу {chat_id}")

                for admin_id in db.get_admins(chat_id):
                    try:
                        admin = bot.get_chat_member(chat_id, admin_id).user
                        if admin.is_bot:
                            logger.info(f"Пропущен админ {admin_id}, так как это бот")
                            continue

                        welcome_message_id = db.get_welcome_message(admin_id)
                        logger.info(f"Для админа {admin_id} найден message_id: {welcome_message_id}")
                        if welcome_message_id:
                            try:
                                bot.edit_message_text(
                                    f"Бот добавлен в группу {update.chat.title}. Выберите группу для управления:",
                                    chat_id=admin_id,
                                    message_id=welcome_message_id,
                                    reply_markup=create_admin_menu(bot, admin_id, db)
                                )
                                logger.info(f"Приветственное сообщение для {admin_id} обновлено: message_id {welcome_message_id}")
                            except Exception as e:
                                logger.error(f"Не удалось отредактировать приветственное сообщение для {admin_id}: {e}")
                                sent_message = bot.send_message(
                                    admin_id,
                                    f"Бот добавлен в группу {update.chat.title}. Выберите группу для управления:",
                                    reply_markup=create_admin_menu(bot, admin_id, db)
                                )
                                db.save_welcome_message(admin_id, sent_message.message_id)
                                logger.info(f"Новое сообщение отправлено для {admin_id}: message_id {sent_message.message_id}")
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
    def handle_new_members(message):
        try:
            chat_id = message.chat.id
            settings = db.get_group_settings(chat_id)
            if not settings.get('greeting_enabled', True):
                return

            # Проверяем права бота на удаление сообщений
            bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
            if bot_member.can_delete_messages:
                try:
                    bot.delete_message(chat_id, message.message_id)
                    logger.info(f"Системное сообщение о присоединении удалено в группе {chat_id}")
                except Exception as e:
                    logger.error(f"Ошибка удаления сообщения о присоединении: {e}")
            else:
                logger.warning(f"Бот не имеет прав на удаление сообщений в группе {chat_id}")

            for member in message.new_chat_members:
                if member.id != bot.get_me().id:
                    bot.send_message(
                        chat_id,
                        f"Добро пожаловать, {member.first_name}! Я бот-администратор. Используйте /help для списка команд."
                    )

        except Exception as e:
            logger.error(f"Ошибка в handle_new_members: {e}")

    @bot.message_handler(content_types=['text'])
    def handle_text(message):
        try:
            chat_id = message.chat.id
            user_id = message.from_user.id
            text = message.text
            settings = db.get_group_settings(chat_id)

            if message.from_user.is_bot or not settings:
                logger.info(f"Сообщение от бота или настройки не найдены: user_id={user_id}, chat_id={chat_id}")
                return
            
            unmute_time = db.get_mute(chat_id, user_id)
            if unmute_time and datetime.now() < unmute_time:
                bot.delete_message(chat_id, message.message_id)
                logger.info(f"Сообщение удалено: пользователь {user_id} в муте до {unmute_time}")
                return
            elif unmute_time:
                db.remove_mute(chat_id, user_id)
                db.reset_warnings(chat_id, user_id)
                logger.info(f"Мут снят для пользователя {user_id} в группе {chat_id}")

            if settings.get('auto_correction', True):
                if is_latin_text(text.lower()):
                    corrected = correct_layout(text.lower())
                    if corrected != text.lower():
                        bot.reply_to(
                            message,
                            f"{corrected}\nИсправлена раскладка в сообщении пользователя {get_username(bot, chat_id, user_id)}.",
                            parse_mode='HTML'
                        )
                        logger.info(f"Исправлена раскладка для текста '{text}' -> '{corrected}'")

            has_profanity = False
            if settings.get('profanity_filter', True):
                if re.search(PROFANITY_REGEX, text.lower(), re.IGNORECASE):
                    has_profanity = True
                    bot.delete_message(chat_id, message.message_id)
                    warnings = db.add_warning(chat_id, user_id)
                    logger.info(f"Обнаружен мат в сообщении от user_id {user_id}, предупреждений: {warnings}")
                    if warnings >= 3:
                        # Проверка прав бота на мут
                        bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
                        if bot_member.can_restrict_members:
                            unmute_time = datetime.now() + timedelta(seconds=24 * 60 * 60)
                            db.add_mute(chat_id, user_id, unmute_time)
                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton(
                                "Размьютить",
                                callback_data=f"unmute_{chat_id}_{user_id}"
                            ))
                            bot.send_message(
                                chat_id,
                                f"Пользователь {get_username(bot, chat_id, user_id)} получил 3 предупреждения и замьючен на 24 часа.",
                                reply_markup=markup,
                                parse_mode='HTML'
                            )
                            logger.info(f"Пользователь {user_id} замьючен на 24 часа")
                        else:
                            logger.warning(f"Бот не имеет прав на ограничение участников в группе {chat_id}")
                            bot.send_message(
                                chat_id,
                                f"Пользователь {get_username(bot, chat_id, user_id)} получил 3 предупреждения, но бот не может замьютить (недостаточно прав).",
                                parse_mode='HTML'
                            )
                    else:
                        bot.send_message(
                            chat_id,
                            f"Предупреждение {warnings}/3 для {get_username(bot, chat_id, user_id)}. Причина: мат",
                            parse_mode='HTML'
                        )
                        
            if not has_profanity and settings.get('toxicity_filter', True):
                toxicity_result = check_message(text)
                if toxicity_result['is_toxic']:
                    bot.delete_message(chat_id, message.message_id)
                    warnings = db.add_warning(chat_id, user_id)
                    logger.info(f"Токсичное сообщение от user_id {user_id} в группе {chat_id}: {text}, предупреждений: {warnings}")
                    if warnings >= 3:
                        bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
                        if bot_member.can_restrict_members:
                            unmute_time = datetime.now() + timedelta(seconds=24 * 60 * 60)
                            db.add_mute(chat_id, user_id, unmute_time)
                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton(
                                "Размьютить",
                                callback_data=f"unmute_{chat_id}_{user_id}"
                            ))
                            bot.send_message(
                                chat_id,
                                f"Пользователь {get_username(bot, chat_id, user_id)} получил 3 предупреждения и замьючен на 24 часа за токсичное сообщение.",
                                reply_markup=markup,
                                parse_mode='HTML'
                            )
                            logger.info(f"Пользователь {user_id} замьючен на 24 часа за токсичность")
                        else:
                            logger.warning(f"Бот не имеет прав на ограничение участников в группе {chat_id}")
                            bot.send_message(
                                chat_id,
                                f"Пользователь {get_username(bot, chat_id, user_id)} получил 3 предупреждения за токсичное сообщение, но бот не может замьютить (недостаточно прав).",
                                parse_mode='HTML'
                            )
                    else:
                        bot.send_message(
                            chat_id,
                            f"Предупреждение {warnings}/3 для {get_username(bot, chat_id, user_id)}. Причина: токсичное сообщение",
                            parse_mode='HTML'
                        )

        except Exception as e:
            logger.error(f"Ошибка в handle_text для сообщения '{text}' в группе {chat_id}: {e}")