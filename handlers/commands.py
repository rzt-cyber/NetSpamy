from telebot import types
import logging
import datetime
import time
from utils import get_username, parse_mute_duration, format_duration, create_main_menu 
from database import Database
from handlers.callbacks import create_admin_menu

logger = logging.getLogger(__name__)

def register_commands(bot, db: Database):
    """Регистрация обработчиков команд"""

    @bot.message_handler(commands=['start'])
    def handle_start(message):
        try:
            if message.chat.type == 'private':
                user_id = message.from_user.id
                admin_groups = [chat_id for chat_id in db.get_all_groups() if user_id in db.get_admins(chat_id)]
                if admin_groups:
                    sent_message = bot.send_message(
                        message.chat.id,
                        "Выберите группу для управления:",
                        reply_markup=create_admin_menu(bot, user_id, db)
                    )
                else:
                    sent_message = bot.send_message(
                        message.chat.id,
                        "Привет! Я бот-администратор. Добавь меня в группу для управления.",
                        reply_markup=create_main_menu()
                    )
                db.save_welcome_message(user_id, sent_message.message_id)
                logger.info(f"Команда /start для user_id {user_id}: message_id {sent_message.message_id} сохранен")
        except Exception as e:
            logger.error(f"Ошибка в /start для user_id {message.from_user.id}: {e}")

    @bot.message_handler(commands=['help'])
    def handle_help(message):
        try:
            bot.send_message(
                message.chat.id,
                "<b>Доступные команды:</b>\n"
                "/mute [время] - Замьютить пользователя (ответ на сообщение)\n"
                "/kick - Исключить пользователя (ответ на сообщение)\n"
                "/ban - Забанить пользователя (ответ на сообщение)\n"
                "/report [причина] - Отправить репорт на пользователя (ответ на сообщение)\n"
                "/reload - Обновить список администраторов группы",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка в /help: {e}")

    @bot.message_handler(commands=['mute', 'kick', 'ban', 'report', 'reload'])
    def handle_moderation_commands(message):
        try:
            if message.chat.type not in ['group', 'supergroup']:
                bot.reply_to(message, "Эта команда работает только в группах.")
                return

            chat_id = message.chat.id
            user_id = message.from_user.id
            admins = db.get_admins(chat_id)

            if user_id not in admins:
                bot.reply_to(message, "Эта команда только для администраторов.")
                return

            command = message.text.split()[0]

            if command == '/reload':
                try:
                    telegram_admins = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
                    db.update_admins(chat_id, telegram_admins)
                    bot.reply_to(
                        message,
                        "Список администраторов успешно обновлен.",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Ошибка при обновлении списка администраторов в группе {chat_id}: {e}")
                    bot.reply_to(
                        message,
                        "Произошла ошибка при обновлении списка администраторов.",
                        parse_mode='HTML'
                    )
                return

            if not message.reply_to_message:
                bot.reply_to(message, "Эта команда должна быть ответом на сообщение.")
                return

            target_user_id = message.reply_to_message.from_user.id

            if command == '/mute':
                duration_str = message.text.split()[1] if len(message.text.split()) > 1 else None
                duration_sec = parse_mute_duration(duration_str)
                unmute_time = datetime.datetime.now() + datetime.timedelta(seconds=duration_sec)
                db.add_mute(chat_id, target_user_id, unmute_time)

                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "Размьютить",
                    callback_data=f"unmute_{chat_id}_{target_user_id}"
                ))

                bot.send_message(
                    chat_id,
                    f"Пользователь {get_username(bot, chat_id, target_user_id)} замьючен на {format_duration(duration_sec)} модератором {get_username(bot, chat_id, user_id)}.",
                    reply_markup=markup,
                    parse_mode='HTML'
                )

            elif command == '/kick':
                bot.kick_chat_member(chat_id, target_user_id, until_date=int(time.time()) + 60)
                bot.reply_to(
                    message,
                    f"Пользователь {get_username(bot, chat_id, target_user_id)} исключен из группы.",
                    parse_mode='HTML'
                )

            elif command == '/ban':
                bot.kick_chat_member(chat_id, target_user_id)
                bot.reply_to(
                    message,
                    f"Пользователь {get_username(bot, chat_id, target_user_id)} забанен.",
                    parse_mode='HTML'
                )

            elif command == '/report':
                reason = ' '.join(message.text.split()[1:]) if len(message.text.split()) > 1 else "Нет причины"
                db.add_report(chat_id, user_id, target_user_id, reason)

                report_msg = (
                    f"Репорт от {get_username(bot, chat_id, user_id)} "
                    f"на {get_username(bot, chat_id, target_user_id)}: {reason}"
                )

                for admin_id in admins:
                    try:
                        bot.send_message(admin_id, report_msg, parse_mode='HTML')
                    except Exception as e:
                        logger.error(f"Ошибка отправки репорта админу {admin_id}: {e}")

                bot.reply_to(message, "Репорт отправлен администраторам.")

        except Exception as e:
            logger.error(f"Ошибка в команде модерации: {e}")