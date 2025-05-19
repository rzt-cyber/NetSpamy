from telebot import types
import logging
import datetime
from datetime import datetime
import time
from utils import get_username, parse_mute_duration, format_duration, create_main_menu 
from database import Database
from handlers.callbacks import create_admin_menu
import threading
import json
from .voting import VotingSystem

logger = logging.getLogger(__name__)

def register_commands(bot, db: Database):
    """Регистрация обработчиков команд"""
    voting = VotingSystem(bot, db)

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
                "/rules - Правила чата\n"
                "/mute [время] - Замьютить пользователя (ответ на сообщение)\n"
                "/unmute - Размьютить пользователя (ответ на сообщение)\n"
                "/kick - Исключить пользователя (ответ на сообщение)\n"
                "/ban - Забанить пользователя (ответ на сообщение)\n"
                "/votemute - Начать голосование за мут пользователя (ответ на сообщение)\n"
                "/voteban - Начать голосование за бан пользователя (ответ на сообщение)\n"
                "/report [причина] - Отправить репорт на пользователя (ответ на сообщение)\n"
                "/reload - Обновить список администраторов группы",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка в /help: {e}")

    @bot.message_handler(commands=['voteban', 'votemute'])
    def handle_vote_command(message):
        if not message.reply_to_message:
            bot.reply_to(message, "❌ Ответьте на сообщение пользователя.")
            return

        chat_id = message.chat.id
        target_user = message.reply_to_message.from_user
        vote_type = "ban" if "ban" in message.text else "mute"

        # Проверка прав
        admins = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
        if target_user.id in admins:
            bot.reply_to(message, "❌ Нельзя голосовать против администратора.")
            return

        # Запуск голосования
        voting.start_vote(chat_id, target_user, message.from_user.id, vote_type)

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
                
                # Применение ограничений через Telegram API
                try:
                    bot.restrict_chat_member(
                        chat_id, target_user_id, 
                        until_date=unmute_time, 
                        can_send_messages=False
                    )
                except Exception as e:
                    logger.error(f"Ошибка при муте пользователя {target_user_id}: {e}")
                    bot.reply_to(
                        message,
                        "❌ Не удалось замьютить. Проверьте права бота (необходимы права администратора с ограничением участников)."
                    )
                    return
                
                # Сохранение в базу данных
                db.add_mute(chat_id, target_user_id, unmute_time)

                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    "Размьютить",
                    callback_data=f"unmute_{chat_id}_{target_user_id}"
                ))

                bot.send_message(
                    chat_id,
                    f"Пользователь {get_username(bot, chat_id, target_user_id)} замьючен на {format_duration(duration_sec)}.",
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
            
    @bot.message_handler(commands=['unmute'])
    def handle_unmute(message):
        try:
            if message.chat.type not in ['group', 'supergroup']:
                bot.reply_to(message, "❌ Команда работает только в группах.")
                return

            chat_id = message.chat.id
            user_id = message.from_user.id

            # Проверка прав администратора
            admins = db.get_admins(chat_id)
            if user_id not in admins:
                bot.reply_to(message, "❌ Только администраторы могут использовать эту команду.")
                return

            # Получение целевого пользователя
            target_user_id = None
            if message.reply_to_message:
                target_user_id = message.reply_to_message.from_user.id
            elif len(message.text.split()) > 1:
                mention = message.text.split()[1]
                if mention.startswith("@"):
                    user = bot.get_chat_member(chat_id, mention)
                    target_user_id = user.user.id

            if not target_user_id:
                bot.reply_to(message, "❌ Упомяните пользователя или ответьте на его сообщение.")
                return

            # Проверка и снятие мута
            mute_data = db.get_mute(chat_id, target_user_id)
            if not mute_data:
                bot.reply_to(message, "ℹ️ Пользователь не замьючен.")
                return

            db.remove_mute(chat_id, target_user_id)
            bot.restrict_chat_member(chat_id, target_user_id, can_send_messages=True)
            bot.reply_to(
                message,
                f"✅ Пользователь {get_username(bot, chat_id, target_user_id)} размьючен.",
                parse_mode='HTML'
            )

        except Exception as e:
            logger.error(f"Ошибка в /unmute: {e}")
            bot.reply_to(message, "❌ Произошла ошибка.")
            
    @bot.message_handler(commands=['rules'])
    def handle_rules(message):
        try:
            chat_id = message.chat.id
            rules_text = db.get_rules(chat_id)
            bot.reply_to(message, f"📜 **Правила чата:**\n\n{rules_text}", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Ошибка в /rules: {e}")
            bot.reply_to(message, "❌ Ошибка при получении правил.")
    
    @bot.message_handler(commands=['setrules'])
    def handle_set_rules(message):
        """Установить правила чата (только для админов)"""
        try:
            if message.chat.type not in ['group', 'supergroup']:
                bot.reply_to(message, "❌ Команда работает только в группах.")
                return

            chat_id = message.chat.id
            user_id = message.from_user.id

            # Проверка прав администратора
            admins = db.get_admins(chat_id)
            if user_id not in admins:
                bot.reply_to(message, "❌ Только администраторы могут изменять правила.")
                return

            # Получение текста правил
            rules_text = message.text.split(' ', 1)[1] if len(message.text.split()) > 1 else None
            if not rules_text:
                bot.reply_to(message, "❌ Укажите текст правил: `/setrules Текст правил...`", parse_mode='Markdown')
                return

            # Сохранение в БД
            db.set_rules(chat_id, rules_text)
            bot.reply_to(message, "✅ Правила чата успешно обновлены!", parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Ошибка в /setrules: {e}")
            bot.reply_to(message, "❌ Произошла ошибка при сохранении правил.")
            
    @bot.message_handler(commands=['setworktime'])
    def handle_set_work_time(message):
        try:
            chat_id = message.chat.id
            user_id = message.from_user.id

            # Проверка, что команда вызвана в группе
            if message.chat.type not in ['group', 'supergroup']:
                bot.reply_to(message, "❌ Команда работает только в группах!")
                return

            # Проверка прав администратора
            admins = db.get_admins(chat_id)
            if user_id not in admins:
                bot.reply_to(message, "❌ Только администраторы могут настраивать режим работы!")
                return

            # Проверка наличия аргументов (например, /setworktime 09:00-18:00)
            args = message.text.split()[1:] if len(message.text.split()) > 1 else []
            if args:
                time_input = " ".join(args)
                process_work_time_input(message, time_input)
            else:
                # Запрос времени, если аргументов нет
                bot.reply_to(message, "⏰ Введите время работы в формате **ЧЧ:ММ-ЧЧ:ММ** (например, 09:00-18:00):", parse_mode="Markdown")
                bot.set_state(user_id, "waiting_work_time", chat_id)

        except Exception as e:
            logger.error(f"Ошибка в /setworktime: {e}")
            bot.reply_to(message, "❌ Произошла ошибка!")
            
    @bot.message_handler(state="waiting_work_time", content_types=['text'])
    def process_work_time_input(message, time_input=None):
        try:
            user_id = message.from_user.id
            chat_id = message.chat.id

            # Если time_input не передан, берем текст сообщения
            if not time_input:
                time_input = message.text.strip()

            # Проверка формата (например, "09:00-18:00")
            if "-" not in time_input:
                raise ValueError("Некорректный формат")

            start_str, end_str = time_input.split("-")
            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.strptime(end_str.strip(), "%H:%M").time()

            # Конвертация в минуты
            work_start = start_time.hour * 60 + start_time.minute
            work_end = end_time.hour * 60 + end_time.minute

            # Сохранение в базу данных
            db.update_work_hours(
                chat_id=chat_id,
                work_start=work_start,
                work_end=work_end,
                timezone="Europe/Moscow"  # Пример, можно добавить выбор часового пояса
            )

            bot.reply_to(
                message,
                f"✅ Режим работы обновлен: {start_str} — {end_str}"
            )
            bot.delete_state(user_id, chat_id)

        except ValueError as e:
            bot.reply_to(message, "❌ Некорректный формат! Пример: `/setworktime 09:00-18:00`", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка сохранения времени: {e}", exc_info=True)
            bot.reply_to(message, "❌ Ошибка при сохранении!")