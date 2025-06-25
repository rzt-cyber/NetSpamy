from telebot import types
import logging
from datetime import datetime, timedelta
from threading import Timer
from utils import get_username, parse_mute_duration, format_duration, create_main_menu
from database import Database
from handlers.callbacks import create_admin_menu, create_settings_menu, waiting_for_report_chat
from config import MESSAGE_LIFETIME_SECONDS

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

def register_commands(bot, db: Database):
    """Регистрация обработчиков команд"""

    @bot.message_handler(commands=['start'])
    def handle_start(message):
        try:
            if message.chat.type == 'private':
                user_id = message.from_user.id
                admin_groups = [chat_id for chat_id in db.get_all_groups() if user_id in db.get_admins(chat_id)]
                existing_message_id = db.get_welcome_message(user_id)
                if admin_groups:
                    if existing_message_id:
                        try:
                            bot.edit_message_text(
                                "Выберите группу для управления:",
                                user_id,
                                existing_message_id,
                                reply_markup=create_admin_menu(bot, user_id, db)
                            )
                            logger.info(f"Обновлено приветственное сообщение для user_id {user_id}: message_id {existing_message_id}")
                        except Exception as e:
                            logger.error(f"Ошибка обновления сообщения для user_id {user_id}: {e}")
                            sent_message = bot.send_message(
                                user_id,
                                "Выберите группу для управления:",
                                reply_markup=create_admin_menu(bot, user_id, db)
                            )
                            db.save_welcome_message(user_id, sent_message.message_id)
                            logger.info(f"Новое приветственное сообщение для user_id {user_id}: message_id {sent_message.message_id}")
                    else:
                        sent_message = bot.send_message(
                            user_id,
                            "Выберите группу для управления:",
                            reply_markup=create_admin_menu(bot, user_id, db)
                        )
                        db.save_welcome_message(user_id, sent_message.message_id)
                        logger.info(f"Новое приветственное сообщение для user_id {user_id}: message_id {sent_message.message_id}")
                else:
                    if existing_message_id:
                        try:
                            bot.edit_message_text(
                                "Привет! Я бот-администратор. Добавь меня в группу для управления.",
                                user_id,
                                existing_message_id,
                                reply_markup=create_main_menu()
                            )
                            logger.info(f"Обновлено приветственное сообщение для user_id {user_id}: message_id {existing_message_id}")
                        except Exception as e:
                            logger.error(f"Ошибка обновления сообщения для user_id {user_id}: {e}")
                            sent_message = bot.send_message(
                                user_id,
                                "Привет! Я бот-администратор. Добавь меня в группу для управления.",
                                reply_markup=create_main_menu()
                            )
                            db.save_welcome_message(user_id, sent_message.message_id)
                            logger.info(f"Новое приветственное сообщение для user_id {user_id}: message_id {sent_message.message_id}")
                    else:
                        sent_message = bot.send_message(
                            user_id,
                            "Привет! Я бот-администратор. Добавь меня в группу для управления.",
                            reply_markup=create_main_menu()
                        )
                        db.save_welcome_message(user_id, sent_message.message_id)
                        logger.info(f"Новое приветственное сообщение для user_id {user_id}: message_id {sent_message.message_id}")
        except Exception as e:
            logger.error(f"Ошибка в /start для user_id {message.from_user.id}: {e}")
            bot.reply_to(message, "❌ Произошла ошибка.")

    @bot.message_handler(commands=['help'])
    def handle_help(message):
        try:
            bot.send_message(
                message.chat.id,
                "<b>Доступные команды:</b>\n"
                "/info - Показать информацию и правила группы\n"
                "/report [причина] - Отправить репорт на пользователя (ответ на сообщение)\n"
                "\n<b>Команды администратора:</b>\n"
                "/mute [время] - Замьютить пользователя (ответ на сообщение)\n"
                "/unmute - Размьютить пользователя (ответ на сообщение или @username)\n"
                "/ban - Забанить пользователя (ответ на сообщение)\n"
                "/reload - Обновить список администраторов группы\n"
                "/setreportchat - Установить текущий чат как канал для репортов (только во время настройки)",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка в /help: {e}")
            bot.reply_to(message, "❌ Произошла ошибка.")

    @bot.message_handler(commands=['info'])
    def handle_info(message):
        try:
            if message.chat.type not in ['group', 'supergroup']:
                bot.reply_to(message, "Эта команда работает только в группах.")
                return
            chat_id = message.chat.id
            info_rules = db.get_info_rules(chat_id)
            sent_message = bot.reply_to(
                message,
                f"📜 Информация и правила:\n\n{info_rules}",
                parse_mode='HTML'
            )
            delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
        except Exception as e:
            logger.error(f"Ошибка в /info: {e}")
            bot.reply_to(message, "❌ Произошла ошибка.")

    @bot.message_handler(commands=['setreportchat'])
    def handle_set_report_chat(message):
        try:
            if message.chat.type not in ['group', 'supergroup']:
                bot.reply_to(message, "Эта команда работает только в группах.")
                return
            user_id = message.from_user.id
            if user_id not in waiting_for_report_chat:
                bot.reply_to(message, "❌ Вы не начали настройку чата для репортов. Начните настройку через меню настроек.")
                return
            wait_data = waiting_for_report_chat.get(user_id)
            expected_group_id = wait_data['group_id']
            db.set_report_chat(expected_group_id, message.chat.id)
            bot.edit_message_text(
                "⚙️ Настройки группы:",
                wait_data['chat_id'],
                wait_data['message_id'],
                reply_markup=create_settings_menu(bot, expected_group_id, user_id, db)
            )
            sent_message = bot.reply_to(message, "✅ Этот чат установлен для получения жалоб. Команды здесь не обрабатываются.")
            # Уведомление в группе для репортов не удаляется
            logger.info(f"Чат {message.chat.id} установлен для репортов группы {expected_group_id} пользователем {user_id}")
        except Exception as e:
            logger.error(f"Ошибка в /setreportchat: {e}")
            bot.reply_to(message, "❌ Произошла ошибка.")

    @bot.message_handler(commands=['mute', 'ban', 'report', 'reload'])
    def handle_moderation_commands(message):
        try:
            if message.chat.type not in ['group', 'supergroup']:
                bot.reply_to(message, "Эта команда работает только в группах.")
                return

            chat_id = message.chat.id
            user_id = message.from_user.id
            admins = db.get_admins(chat_id)

            if user_id not in admins and message.text.split()[0] != '/report':
                sent_message = bot.reply_to(message, "Эта команда только для администраторов.")
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                return

            command = message.text.split()[0]

            if command == '/reload':
                try:
                    telegram_admins = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
                    db.update_admins(chat_id, telegram_admins)
                    sent_message = bot.reply_to(
                        message,
                        "Список администраторов успешно обновлен.",
                        parse_mode='HTML'
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                except Exception as e:
                    logger.error(f"Ошибка при обновлении списка администраторов в группе {chat_id}: {e}")
                    sent_message = bot.reply_to(
                        message,
                        "Произошла ошибка при обновлении списка администраторов.",
                        parse_mode='HTML'
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                return

            if not message.reply_to_message:
                sent_message = bot.reply_to(message, "❌ Эта команда должна быть ответом на сообщение.")
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                return

            target_user_id = message.reply_to_message.from_user.id
            message_id = message.reply_to_message.message_id

            if command == '/mute':
                duration_str = message.text.split()[1] if len(message.text.split()) > 1 else None
                duration_sec = parse_mute_duration(duration_str)
                unmute_time = datetime.now() + timedelta(seconds=duration_sec)

                try:
                    bot.restrict_chat_member(
                        chat_id,
                        target_user_id,
                        until_date=unmute_time,
                        permissions=types.ChatPermissions(can_send_messages=False)
                    )
                except Exception as e:
                    logger.error(f"Ошибка при муте пользователя {target_user_id}: {e}")
                    sent_message = bot.reply_to(
                        message,
                        "❌ Не удалось замьютить. Проверьте права бота (необходимы права администратора с ограничением участников)."
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    return

                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "Размьютить",
                    callback_data=f"unmute_{chat_id}_{target_user_id}"
                ))

                sent_message = bot.send_message(
                    chat_id,
                    f"Пользователь {get_username(bot, chat_id, target_user_id)} замьючен на {format_duration(duration_sec)}.",
                    reply_markup=markup,
                    parse_mode='HTML'
                )
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)

            elif command == '/ban':
                try:
                    bot.kick_chat_member(chat_id, target_user_id)
                    sent_message = bot.reply_to(
                        message,
                        f"Пользователь {get_username(bot, chat_id, target_user_id)} забанен.",
                        parse_mode='HTML'
                    )
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                except Exception as e:
                    logger.error(f"Ошибка при бане пользователя {target_user_id}: {e}")
                    sent_message = bot.reply_to(message, "❌ Не удалось забанить пользователя.")
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)

            elif command == '/report':
                settings = db.get_group_settings(chat_id)
                if not settings.get('report_system', False):
                    sent_message = bot.reply_to(message, "⚠️ Система жалоб отключена. Обратитесь к администратору для её включения.")
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    return

                reason = ' '.join(message.text.split()[1:]) if len(message.text.split()) > 1 else "Нет причины"
                db.add_report(chat_id, user_id, target_user_id, reason, message_id)

                report_msg = (
                    f"Жалоба от: {get_username(bot, chat_id, user_id)}\n"
                    f"На: {get_username(bot, chat_id, target_user_id)}\n"
                    f"Причина: {reason}"
                )

                log_chat_id = db.get_report_chat(chat_id)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "Перейти к сообщению",
                    url=f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
                ))

                if log_chat_id:
                    try:
                        bot.send_message(log_chat_id, report_msg, reply_markup=markup, parse_mode='HTML')
                        sent_message = bot.reply_to(message, "Жалоба отправлена в чат для репортов.")
                        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                    except Exception as e:
                        logger.error(f"Ошибка отправки репорта в лог-чат {log_chat_id}: {e}")
                        sent_message = bot.reply_to(message, "❌ Не удалось отправить жалобу в чат для репортов.")
                        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                else:
                    sent_message = bot.reply_to(message, "⚠️ Чат для репортов не настроен. Обратитесь к администратору.")
                    delete_message_after_delay(bot, chat_id, sent_message.message_id, db)

        except Exception as e:
            logger.error(f"Ошибка в команде модерации: {e}")
            sent_message = bot.reply_to(message, "❌ Произошла ошибка.")
            delete_message_after_delay(bot, chat_id, sent_message.message_id, db)

    @bot.message_handler(commands=['unmute'])
    def handle_unmute(message):
        try:
            if message.chat.type not in ['group', 'supergroup']:
                sent_message = bot.reply_to(message, "❌ Команда работает только в группах.")
                delete_message_after_delay(bot, message.chat.id, sent_message.message_id, db)
                return

            chat_id = message.chat.id
            user_id = message.from_user.id

            admins = db.get_admins(chat_id)
            if user_id not in admins:
                sent_message = bot.reply_to(message, "❌ Только администраторы могут использовать эту команду.")
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                return

            target_user_id = None
            if message.reply_to_message:
                target_user_id = message.reply_to_message.from_user.id
            elif len(message.text.split()) > 1:
                mention = message.text.split()[1]
                if mention.startswith('@'):
                    try:
                        user = bot.get_chat_member(chat_id, mention).user
                        target_user_id = user.id
                    except Exception as e:
                        logger.error(f"Ошибка получения пользователя по упоминанию {mention}: {e}")
                        sent_message = bot.reply_to(message, "❌ Не удалось найти пользователя.")
                        delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                        return

            if not target_user_id:
                sent_message = bot.reply_to(message, "❌ Упомяните пользователя (@username) или ответьте на его сообщение.")
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                return

            try:
                bot.restrict_chat_member(
                    chat_id,
                    target_user_id,
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
                sent_message = bot.reply_to(
                    message,
                    f"✅ Пользователь {get_username(bot, chat_id, target_user_id)} размьючен.",
                    parse_mode='HTML'
                )
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)
                db.reset_warnings(chat_id, target_user_id)
            except Exception as e:
                logger.error(f"Ошибка при размьюте пользователя {target_user_id}: {e}")
                sent_message = bot.reply_to(message, "❌ Не удалось размьютить пользователя.")
                delete_message_after_delay(bot, chat_id, sent_message.message_id, db)

        except Exception as e:
            logger.error(f"Ошибка в /unmute: {e}")
            sent_message = bot.reply_to(message, "❌ Произошла ошибка.")
            delete_message_after_delay(bot, message.chat.id, sent_message.message_id, db)