from telebot import types
import re
import time
import logging
import sqlite3
from .security import is_dangerous_file, handle_dangerous_file
from datetime import datetime, timedelta
from config import PROFANITY_REGEX
from utils import (
    is_latin_text, correct_layout, get_username, check_message, create_main_menu, 
    get_current_time_in_timezone, minutes_to_time, is_chat_open, 
    unrestrict_all_members, restrict_all_members, unrestrict_user
)
from database import Database
from handlers.callbacks import create_admin_menu, create_settings_menu

logger = logging.getLogger(__name__)

def handle_chat_status(bot, db, chat_id, force_notification=False):
    """Проверяет и обновляет статус чата"""
    try:
        work_hours = db.get_work_hours(chat_id)
        if not work_hours:
            return
            
        work_start, work_end, timezone = work_hours
        current_time = get_current_time_in_timezone(timezone)
        is_open = is_chat_open(current_time, work_start, work_end)
        current_closed_status = db.is_chat_closed(chat_id)

        # Если статус изменился или принудительное уведомление
        if force_notification or (is_open != (not current_closed_status)):
            if is_open:
                db.set_chat_closed(chat_id, False)
                # Отправляем уведомление только при изменении статуса
                if force_notification or not current_closed_status:
                    bot.send_message(
                        chat_id, 
                        f"🔓 Чат открыт! Режим работы: {minutes_to_time(work_start)}-{minutes_to_time(work_end)} ({timezone})"
                    )
            else:
                db.set_chat_closed(chat_id, True)
                # Отправляем уведомление только при изменении статуса
                if force_notification or current_closed_status:
                    bot.send_message(
                        chat_id,
                        f"🔒 Чат закрыт! Следующее открытие: {minutes_to_time(work_start)} ({timezone})\n"
                        "Сообщения будут удаляться, а отправители временно ограничиваться."
                    )
    except Exception as e:
        logger.error(f"Ошибка проверки статуса чата: {e}")

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

    @bot.message_handler(content_types=['left_chat_member'])
    def handle_left_member(message):    
        try:
            chat_id = message.chat.id
            if not message.left_chat_member:            
                return
            left_member = message.left_chat_member
            if left_member.id == bot.get_me().id:
                return
            try:            
                if message.chat.type in ['group', 'supergroup']:
                    bot.delete_message(chat_id, message.message_id)        
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение о выходе: {e}")
            bot.send_message(
                chat_id,            f"😢 {left_member.first_name} покинул(а) чат",
                parse_mode='HTML'        )
        except Exception as e:
            logger.error(f"Ошибка в обработчике выхода участника: {e}")


    # Изменение режима работы
    @bot.message_handler(func=lambda msg: msg.reply_to_message is not None 
                  and "⏰ Введите новый режим работы" in msg.reply_to_message.text
                  and msg.reply_to_message.from_user.id == bot.get_me().id)
    def handle_worktime_reply(message):
        try:
            user_id = message.from_user.id
            original_text = message.reply_to_message.text
            group_id = int(original_text.split("ID: ")[1].split(")")[0])
            
            # Проверка прав
            admins = db.get_admins(group_id)
            if user_id not in admins:
                bot.reply_to(message, "❌ Вы не администратор!")
                return

            # Парсим ввод (пример: "09:00-18:00 Europe/Moscow")
            time_input = message.text.strip()
            if "-" not in time_input:
                raise ValueError("Некорректный формат времени")

            # Разделяем время и часовой пояс
            parts = time_input.split()
            if len(parts) < 2:
                timezone = "UTC"  # Значение по умолчанию
                time_range = parts[0]
            else:
                time_range = parts[0]
                timezone = " ".join(parts[1:])  # Объединяем оставшиеся части как часовой пояс

            # Валидация часового пояса
            try:
                import pytz  # Убедитесь, что библиотека установлена (pip install pytz)
                pytz.timezone(timezone)  # Проверяем валидность часового пояса
            except pytz.UnknownTimeZoneError:
                timezone = "UTC"  # Если часовой пояс не распознан, используем UTC
                bot.reply_to(message, "⚠️ Используется UTC (неизвестный часовой пояс)")

            # Парсим время
            start_str, end_str = time_range.split("-")
            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
            
            # Конвертация в минуты
            work_start = start_time.hour * 60 + start_time.minute
            work_end = end_time.hour * 60 + end_time.minute

            # Сохраняем в БД
            db.update_work_hours(group_id, work_start, work_end, timezone)
            
            # Удаляем сообщения
            try:
                bot.delete_message(message.chat.id, message.reply_to_message.message_id)
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            
            # Возвращаем меню
            bot.send_message(
                message.chat.id,
                f"✅ Режим работы обновлен:\n"
                f"• Время: {start_str}-{end_str}\n"
                f"• Часовой пояс: {timezone}",
                reply_markup=create_admin_menu(bot, user_id, db)
            )

        except ValueError as e:
            bot.reply_to(message, "❌ Неверный формат! Пример: `09:00-18:00 Europe/Moscow`", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка обновления режима работы: {str(e)}")
            bot.reply_to(message, "❌ Ошибка сохранения!")
    
    # Обработка запроса на изменение правил чата
    @bot.message_handler(func=lambda msg: msg.reply_to_message is not None 
                      and msg.reply_to_message.text.startswith("✍️ Введите новые правила")
                      and msg.reply_to_message.from_user.id == bot.get_me().id)
    def handle_rules_reply(message):
        try:
            user_id = message.from_user.id
            original_text = message.reply_to_message.text
            
            # Извлекаем chat_id из оригинального сообщения
            group_id = int(original_text.split("ID: ")[1].split(")")[0])
            
            # Проверка прав администратора
            admins = db.get_admins(group_id)
            if user_id not in admins:
                bot.reply_to(message, "❌ Вы не администратор этой группы!")
                return

            # Сохраняем правила
            db.set_rules(group_id, message.text)
            
            # Удаляем сообщение с запросом правил
            bot.delete_message(message.chat.id, message.reply_to_message.message_id)
            
            # Удаляем сообщение с новыми правилами от пользователя
            bot.delete_message(message.chat.id, message.message_id)
            
            # Отправляем подтверждение и возвращаем меню
            bot.send_message(
                message.chat.id,
                f"✅ Правила для группы {group_id} обновлены!",
                #reply_markup=create_admin_menu(bot, user_id, db)  # <-- Возврат меню
            )
            
            bot.send_message(
                message.chat.id,
                f"Выберите группу для управления",
                reply_markup=create_admin_menu(bot, user_id, db)
            )

        except Exception as e:
            logger.error(f"Ошибка обработки правил: {e}")
            bot.reply_to(message, "❌ Ошибка сохранения правил!")
    

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
    
    @bot.message_handler(content_types=['text', 'photo', 'video', 'document'])
    def unified_message_handler(message):
        try:
            chat_id = message.chat.id
            user_id = message.from_user.id
            
            # Пропустить служебные сообщения и сообщения в ЛС
            if message.chat.type not in ['group', 'supergroup']:
                return

            # Получаем настройки группы
            settings = db.get_group_settings(chat_id)
            if not settings:
                return

            # Проверка прав бота
            bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
            if not bot_member.can_delete_messages:
                logger.warning(f"Бот не имеет прав на удаление сообщений в {chat_id}")
                return

            # Проверка статуса чата (рабочее время)
            work_hours = db.get_work_hours(chat_id)
            if work_hours:
                work_start, work_end, timezone = work_hours
                current_time = get_current_time_in_timezone(timezone)
                is_open = is_chat_open(current_time, work_start, work_end)
                
                if not is_open:
                    # Удаление сообщения и ограничение пользователя
                    try:
                        bot.delete_message(chat_id, message.message_id)
                        
                        until_date = int(time.time()) + 3600
                        bot.restrict_chat_member(
                            chat_id=chat_id,
                            user_id=user_id,
                            until_date=until_date,
                            permissions=types.ChatPermissions(
                                can_send_messages=False,
                                can_send_media_messages=False,
                                can_send_polls=False,
                                can_send_other_messages=False,
                                can_add_web_page_previews=False,
                                can_change_info=False,
                                can_invite_users=False,
                                can_pin_messages=False
                            )
                        )
                        bot.send_message(
                            chat_id,
                            f"Пользователь {get_username(bot, chat_id, user_id)} ограничен на 1 час "
                            f"за попытку отправить сообщение в закрытом чате.",
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Ошибка обработки закрытого чата: {e}")
                    return  # Прекращаем обработку

            # Проверка мута пользователя
            unmute_time = db.get_mute(chat_id, user_id)
            if unmute_time and datetime.now() < unmute_time:
                try:
                    bot.delete_message(chat_id, message.message_id)
                    logger.info(f"Сообщение удалено: пользователь {user_id} в муте до {unmute_time}")
                except Exception as e:
                    logger.error(f"Ошибка удаления сообщения в муте: {e}")
                return
            elif unmute_time:
                db.remove_mute(chat_id, user_id)
                db.reset_warnings(chat_id, user_id)
                logger.info(f"Мут снят для пользователя {user_id} в группе {chat_id}")

            # Проверяем только текстовые сообщения
            if message.content_type != 'text':
                return

            text = message.text

            # Автокоррекция раскладки
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

            # Проверка на мат
            has_profanity = False
            if settings.get('profanity_filter', True):
                if re.search(PROFANITY_REGEX, text.lower(), re.IGNORECASE):
                    has_profanity = True
                    try:
                        bot.delete_message(chat_id, message.message_id)
                        warnings = db.add_warning(chat_id, user_id)
                        logger.info(f"Обнаружен мат в сообщении от user_id {user_id}, предупреждений: {warnings}")
                        
                        if warnings >= 3:
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
                            else:
                                bot.send_message(
                                    chat_id,
                                    f"Пользователь {get_username(bot, chat_id, user_id)} получил 3 предупреждения, но бот не может замьютить.",
                                    parse_mode='HTML'
                                )
                        else:
                            bot.send_message(
                                chat_id,
                                f"Предупреждение {warnings}/3 для {get_username(bot, chat_id, user_id)}. Причина: мат",
                                parse_mode='HTML'
                            )
                    except Exception as e:
                        logger.error(f"Ошибка обработки мата: {e}")

            # Проверка на токсичность (если не было мата)
            if not has_profanity and settings.get('toxicity_filter', True):
                try:
                    toxicity_result = check_message(text)
                    if toxicity_result.get('is_toxic', False):
                        try:
                            bot.delete_message(chat_id, message.message_id)
                            warnings = db.add_warning(chat_id, user_id)
                            logger.info(f"Токсичное сообщение от user_id {user_id}: {text}, предупреждений: {warnings}")
                            
                            if warnings >= 3:
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
                                        f"Пользователь {get_username(bot, chat_id, user_id)} замьючен на 24 часа за токсичное сообщение.",
                                        reply_markup=markup,
                                        parse_mode='HTML'
                                    )
                                else:
                                    bot.send_message(
                                        chat_id,
                                        f"Пользователь {get_username(bot, chat_id, user_id)} получил 3 предупреждения, но бот не может замьютить.",
                                        parse_mode='HTML'
                                    )
                            else:
                                bot.send_message(
                                    chat_id,
                                    f"Предупреждение {warnings}/3 для {get_username(bot, chat_id, user_id)}. Причина: токсичность",
                                    parse_mode='HTML'
                                )
                        except Exception as e:
                            logger.error(f"Ошибка обработки токсичности: {e}")
                except Exception as e:
                    logger.error(f"Ошибка проверки токсичности: {e}")

        except Exception as e:
            logger.error(f"Критическая ошибка в unified_message_handler: {e}")
