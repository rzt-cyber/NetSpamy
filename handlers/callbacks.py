from telebot import types
from telebot.handler_backends import StatesGroup, State
import logging
import time
from utils import get_username, create_main_menu
from database import Database 
from .voting import VotingSystem

logger = logging.getLogger(__name__)

def create_admin_menu(bot, user_id, db: Database):
    """Создает меню администратора с актуальным списком групп"""
    markup = types.InlineKeyboardMarkup()
    
    # Получаем группы, где пользователь является администратором
    user_groups = [
        chat_id for chat_id in db.get_all_groups() 
        if user_id in db.get_admins(chat_id)
    ]
    
    for chat_id in user_groups:
        try:
            chat = bot.get_chat(chat_id)
            markup.add(types.InlineKeyboardButton(
                chat.title,
                callback_data=f"settings_{chat_id}"
            ))
        except Exception as e:
            logger.error(f"Ошибка получения информации о чате {chat_id}: {e}")
    
    markup.add(types.InlineKeyboardButton(
        "Добавить новую группу",
        callback_data="add_group"
    ))
    return markup

def create_settings_menu(bot, chat_id, user_id, db: Database):
    """Создает меню настроек группы"""
    logger.info(f"Создание меню настроек для группы {chat_id} пользователем {user_id}")
    markup = types.InlineKeyboardMarkup()
    settings = db.get_group_settings(chat_id)
    
    buttons = [
        ('greeting_enabled', 'Приветствие'),
        ('profanity_filter', 'Фильтр матов'),
        ('auto_correction', 'Автокоррекция языка'),
        ('toxicity_filter', 'Фильтр токсичности'),
        ('file_filter', 'Фильтр файлов'),
    ]
    
    for setting, text in buttons:
        btn_text = f"{text}: {'Вкл' if settings.get(setting, False) else 'Выкл'}"
        markup.add(types.InlineKeyboardButton(
            btn_text,
            callback_data=f"toggle:{setting}:{chat_id}"
        ))
    
    markup.add(types.InlineKeyboardButton(
        "⏰ Режим работы",
        callback_data=f"edit_worktime_{chat_id}"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "📝 Правила чата",
        callback_data=f"edit_rules_{chat_id}"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "💬 Команды",
        callback_data=f"commands_{chat_id}"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "← Назад",
        callback_data="back_to_groups"
    ))
    
    
    logger.info(f"Меню настроек для группы {chat_id} создано успешно: {settings}")
    return markup

def register_callbacks(bot, db: Database):
    """Регистрация обработчиков callback-запросов"""
    logger.info("Регистрация обработчиков callback-запросов")
    voting = VotingSystem(bot, db)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('vote_'))
    def handle_vote_callback(call):
        voting.handle_vote(call)
    
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback(call):
        try:
            logger.info(f"Получен callback-запрос от user_id {call.from_user.id}: {call.data}")
            chat_id = call.message.chat.id
            user_id = call.from_user.id
            data = call.data

            if data.startswith('unmute_'):
                logger.info(f"Обработка unmute для группы и пользователя: {data}")
                _, group_id, muted_user_id = data.split('_')
                group_id = int(group_id)
                muted_user_id = int(muted_user_id)
                
                admins = db.get_admins(group_id)
                if user_id not in admins:
                    bot.answer_callback_query(
                        call.id,
                        "Вы не являетесь администратором!",
                        show_alert=True
                    )
                    return
                
                if db.get_mute(group_id, muted_user_id):
                    db.remove_mute(group_id, muted_user_id)
                    db.reset_warnings(group_id, muted_user_id)
                    
                    bot.edit_message_text(
                        f"Пользователь {get_username(bot, group_id, muted_user_id)} размьючен, предупреждения сброшены.",
                        chat_id,
                        call.message.message_id,
                        parse_mode='HTML'
                    )
                else:
                    bot.answer_callback_query(
                        call.id,
                        "Пользователь уже размьючен.",
                        show_alert=True
                    )

            elif data.startswith('settings_'):
                group_id = int(data.split('_')[1])
                logger.info(f"Открытие настроек для группы {group_id} пользователем {user_id}")
                if user_id in db.get_admins(group_id):
                    try:
                        try:
                            bot.edit_message_text(
                                "⚙️ Настройки группы:",
                                chat_id=chat_id,
                                message_id=call.message.message_id,
                                reply_markup=create_settings_menu(bot, group_id, user_id, db)
                            )
                        except Exception as e:
                            logger.error(f"Ошибка редактирования сообщения: {e}")
                            # Отправляем новое сообщение, если редактирование невозможно
                            sent_msg = bot.send_message(
                                chat_id,
                                "⚙️ Настройки группы:",
                                reply_markup=create_settings_menu(bot, group_id, user_id, db)
                            )
                            # Удаляем старое сообщение (опционально)
                            try:
                                bot.delete_message(chat_id, call.message.message_id)
                            except:
                                pass
                        logger.info(f"Сообщение отредактировано для группы {group_id}: message_id {call.message.message_id}")
                    except Exception as e:
                        logger.error(f"Ошибка редактирования сообщения для группы {group_id}: {e}")
                        sent_message = bot.send_message(
                            chat_id,
                            f"Настройки группы:",
                            reply_markup=create_settings_menu(bot, group_id, user_id, db)
                        )
                        db.save_welcome_message(user_id, sent_message.message_id)
                        logger.info(f"Новое сообщение отправлено для user_id {user_id}: message_id {sent_message.message_id}")
                else:
                    logger.warning(f"Пользователь {user_id} не является админом группы {group_id}")
                    bot.answer_callback_query(
                        call.id,
                        "Вы не являетесь администратором этой группы!",
                        show_alert=True
                    )

            elif data == 'add_group':
                logger.info(f"Пользователь {user_id} запросил добавление новой группы")
                bot.edit_message_text(
                    "Добавьте бота в группу через кнопку 'Добавить бота'",
                    chat_id,
                    call.message.message_id,
                    reply_markup=create_main_menu()
                )

            elif data.startswith('edit_worktime_'):
                group_id = int(data.split('_')[2])
                admins = db.get_admins(group_id)
                
                if user_id not in admins:
                    bot.answer_callback_query(call.id, "❌ Только администраторы!", show_alert=True)
                    return

                try:
                    # Удаляем старое сообщение
                    bot.delete_message(chat_id, call.message.message_id)
                except:
                    pass

                # Отправляем запрос на ввод времени
                markup = types.ForceReply(input_field_placeholder="Пример: 09:00-18:00 Europe/Moscow")
                sent_msg = bot.send_message(
                    chat_id,
                    f"⏰ Введите новый режим работы для чата (ID: {group_id}) в формате:\n"
                    "ЧЧ:ММ-ЧЧ:ММ ЧасовойПояс\n"
                    "Примеры:\n"
                    "- 09:00-18:00 Europe/Moscow\n"
                    "- 00:00-23:59 UTC\n",
                    reply_markup=markup
                )

            elif data.startswith('edit_rules_'):
                group_id = int(data.split('_')[2])
                admins = db.get_admins(group_id)
                
                if user_id not in admins:
                    bot.answer_callback_query(call.id, "❌ Только администраторы!", show_alert=True)
                    return

                try:
                    # Удаляем старое сообщение с кнопкой
                    bot.delete_message(chat_id, call.message.message_id)
                except:
                    pass

                # Отправляем новое сообщение с ForceReply
                markup = types.ForceReply(input_field_placeholder="Напишите новые правила...")
                sent_msg = bot.send_message(
                    chat_id,
                    f"✍️ Введите новые правила для чата (ID: {group_id}):",
                    reply_markup=markup
                )
            
            elif data == 'back_to_groups':
                logger.info(f"Пользователь {user_id} возвращается к списку групп")
                bot.edit_message_text(
                    "Ваши группы:",
                    chat_id,
                    call.message.message_id,
                    reply_markup=create_admin_menu(bot, user_id, db)
                )

            elif data.startswith('toggle:'):
                logger.info(f"Обработка toggle для настройки: {data}")
                parts = data.split(':')
                logger.info(f"Разделённые части callback-данных: {parts}")
                if len(parts) == 3:
                    _, setting, group_id_str = parts
                    try:
                        group_id = int(group_id_str)
                    except ValueError as e:
                        logger.error(f"Ошибка преобразования group_id в число: {group_id_str}, ошибка: {e}")
                        bot.answer_callback_query(call.id, "Ошибка: некорректный идентификатор группы.", show_alert=True)
                        return
                    
                    logger.info(f"Пользователь {user_id} пытается изменить настройку {setting} для группы {group_id}")
                    admins = db.get_admins(group_id)
                    if user_id in admins:
                        settings = db.get_group_settings(group_id)
                        if not settings:
                            logger.error(f"Настройки для группы {group_id} не найдены")
                            bot.answer_callback_query(call.id, "Ошибка: настройки группы не найдены.", show_alert=True)
                            return
                        old_value = settings.get(setting, False)
                        new_value = not old_value
                        logger.info(f"Попытка обновления настройки {setting} для группы {group_id}: {old_value} -> {new_value}")
                        db.update_group_setting(group_id, setting, new_value)
                        updated_settings = db.get_group_settings(group_id)
                        if updated_settings.get(setting) != new_value:
                            logger.error(f"Настройка {setting} для группы {group_id} не обновилась: ожидалось {new_value}, получено {updated_settings.get(setting)}")
                            bot.answer_callback_query(call.id, "Ошибка при обновлении настройки.", show_alert=True)
                            return
                        bot.edit_message_text(
                            f"Настройки группы: {setting} изменено на {'Вкл' if new_value else 'Выкл'}",
                            chat_id=chat_id,
                            message_id=call.message.message_id,
                            reply_markup=create_settings_menu(bot, group_id, user_id, db)
                        )
                        bot.answer_callback_query(call.id, f"Настройка {setting} изменена на {'Вкл' if new_value else 'Выкл'}.")
                        logger.info(f"Меню настроек обновлено для группы {group_id}: message_id {call.message.message_id}")
                    else:
                        logger.warning(f"Пользователь {user_id} не является админом группы {group_id}")
                        bot.answer_callback_query(
                            call.id,
                            "Вы не являетесь администратором этой группы!",
                            show_alert=True
                        )
                else:
                    logger.error(f"Некорректный формат callback-данных: {data}, ожидалось toggle:setting:group_id")
                    bot.answer_callback_query(call.id, "Ошибка: некорректный запрос.", show_alert=True)

            elif data.startswith('commands_'):
                group_id = int(data.split('_')[1])
                logger.info(f"Пользователь {user_id} запросил список команд для группы {group_id}")
                bot.edit_message_text(
                    "<b>Доступные команды:</b>\n"
                    "/rules - Правила чата\n"
                    "/votemute - Начать голосование за мут пользователя (ответ на сообщение)\n"
                    "/voteban - Начать голосование за бан пользователя (ответ на сообщение)\n"
                    "/report [причина] - Отправить репорт на пользователя (ответ на сообщение)\n"
                    "\n<b>Команды администратора:</b>\n"
                    "/setrules - установить новые правила чата\n"
                    "/mute [время] - Замьютить пользователя (ответ на сообщение)\n"
                    "/unmute - Размьютить пользователя (ответ на сообщение)\n"
                    "/kick - Исключить пользователя (ответ на сообщение)\n"
                    "/ban - Забанить пользователя (ответ на сообщение)\n"
                    "/reload - Обновить список администраторов группы",
                    chat_id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=types.InlineKeyboardMarkup().add(
                        types.InlineKeyboardButton(
                            "Назад",
                            callback_data=f"settings_{group_id}"
                        )
                    )
                )

            bot.answer_callback_query(call.id)
            logger.info(f"Callback-запрос от user_id {user_id} обработан успешно")

        except Exception as e:
            logger.error(f"Ошибка в callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка, попробуйте позже.", show_alert=True)

    logger.info("Обработчики callback-запросов зарегистрированы успешно")