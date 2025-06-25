from telebot import types
import logging
from utils import get_username, create_main_menu, unrestrict_user
from database import Database 

logger = logging.getLogger(__name__)

waiting_for_rules = {}
waiting_for_report_chat = {}

def create_admin_menu(bot, user_id, db: Database):
    markup = types.InlineKeyboardMarkup()
    user_groups = [chat_id for chat_id in db.get_all_groups() if user_id in db.get_admins(chat_id)]
    for chat_id in user_groups:
        try:
            chat = bot.get_chat(chat_id)
            markup.add(types.InlineKeyboardButton(chat.title, callback_data=f"settings_{chat_id}"))
        except Exception as e:
            logger.error(f"Ошибка получения информации о чате {chat_id}: {e}")
    markup.add(types.InlineKeyboardButton(
        "Добавить новую группу",
        url=db.get_bot_invite_url()
    ))
    return markup

def create_settings_menu(bot, chat_id, user_id, db: Database):
    logger.info(f"Создание меню настроек для группы {chat_id} пользователем {user_id}")
    markup = types.InlineKeyboardMarkup()
    settings = db.get_group_settings(chat_id)
    buttons = [
        ('greeting_enabled', 'Приветствие', 'Включает/выключает автоматическое приветственное сообщение для новых участников группы.'),
        ('profanity_filter', 'Фильтр матов', 'Обнаруживает и удаляет сообщения с нецензурной лексикой, выдавая предупреждения.'),
        ('toxicity_filter', 'Фильтр токсичности', 'Обнаруживает токсичные сообщения с помощью ИИ, выдавая предупреждения.'),
        ('file_filter', 'Фильтр файлов', 'Блокирует отправку потенциально опасных файлов (например, .exe, .bat) и наказывает отправителя.'),
        ('report_system', 'Система жалоб', 'Добавляет команду /report. Вернитесь назад и нажмите на кнопку "Система жалоб", чтобы её настроить.'),
        ('link_filter', 'Фильтр ссылок', 'Обнаруживает и удаляет сообщения, содержащие ссылки, выдавая предупреждения.'),
        ('captcha_enabled', 'Капча для новых', 'Требует от новых участников пройти капчу перед отправкой сообщений.')
    ]
    for setting, text, description in buttons:
        status = '✅' if settings.get(setting, False) else '❌'
        btn_text = f"{text}: {status}"
        markup.row(
            types.InlineKeyboardButton(btn_text, callback_data=f"toggle:{setting}:{chat_id}"),
            types.InlineKeyboardButton("ℹ️", callback_data=f"info:{setting}:{chat_id}")
        )
    if settings.get('report_system', False):
        log_chat_id = db.get_report_chat(chat_id)
        if not log_chat_id:
            markup.add(types.InlineKeyboardButton("⚙️ Настроить систему жалоб", callback_data=f"report_chat_{chat_id}"))
    markup.add(types.InlineKeyboardButton("📜 Информация и правила", callback_data=f"info_rules_{chat_id}"))
    markup.add(types.InlineKeyboardButton("💬 Команды", callback_data=f"commands_{chat_id}"))
    log_chat_id = db.get_report_chat(chat_id)
    if log_chat_id:
        markup.add(types.InlineKeyboardButton(f"Изменить чат для репортов (ID: {log_chat_id})", callback_data=f"report_chat_{chat_id}"))
    markup.add(types.InlineKeyboardButton("← Назад", callback_data="back_to_groups"))
    logger.info(f"Меню настроек для группы {chat_id} создано успешно: {settings}")
    return markup

def register_callbacks(bot, db: Database):
    logger.info("Регистрация обработчиков callback-запросов")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('unmute_'))
    def handle_unmute_callback(call):
        try:
            _, group_id, muted_user_id = call.data.split('_')
            group_id = int(group_id)
            muted_user_id = int(muted_user_id)
            user_id = call.from_user.id
            admins = db.get_admins(group_id)
            if user_id not in admins:
                bot.answer_callback_query(call.id, "Вы не являетесь администратором!", show_alert=True)
                return
            try:
                bot.restrict_chat_member(
                    group_id,
                    muted_user_id,
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
                db.reset_warnings(group_id, muted_user_id)
                bot.edit_message_text(
                    f"Пользователь {get_username(bot, group_id, muted_user_id)} размьючен, предупреждения сброшены.",
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Ошибка при размьюте пользователя {muted_user_id}: {e}")
                bot.answer_callback_query(call.id, "Не удалось размьютить пользователя.", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка в unmute callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('captcha_'))
    def handle_captcha_callback(call):
        try:
            _, group_id, user_id = call.data.split('_')
            group_id = int(group_id)
            user_id = int(user_id)
            if call.from_user.id != user_id:
                bot.answer_callback_query(call.id, "Эта капча предназначена не для вас!", show_alert=True)
                return
            if db.has_passed_captcha(group_id, user_id):
                bot.answer_callback_query(call.id, "Вы уже прошли капчу!", show_alert=True)
                return
            db.set_captcha_passed(group_id, user_id)
            unrestrict_user(bot, group_id, user_id)
            bot.edit_message_text(
                f"✅ {get_username(bot, group_id, user_id)} успешно прошел капчу и может писать в чат!",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML'
            )
            logger.info(f"Пользователь {user_id} прошел капчу в группе {group_id}")
        except Exception as e:
            logger.error(f"Ошибка в captcha callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('settings_'))
    def handle_settings_callback(call):
        try:
            group_id = int(call.data.split('_')[1])
            user_id = call.from_user.id
            if user_id in db.get_admins(group_id):
                bot.edit_message_text(
                    "⚙️ Настройки группы:",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=create_settings_menu(bot, group_id, user_id, db)
                )
            else:
                bot.answer_callback_query(call.id, "Вы не являетесь администратором этой группы!", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка в settings callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data == 'back_to_groups')
    def handle_back_to_groups_callback(call):
        user_id = call.from_user.id
        bot.edit_message_text(
            "Ваши группы:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_admin_menu(bot, user_id, db)
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith('toggle:'))
    def handle_toggle_setting_callback(call):
        parts = call.data.split(':')
        if len(parts) == 3:
            _, setting, group_id_str = parts
            try:
                group_id = int(group_id_str)
            except ValueError:
                bot.answer_callback_query(call.id, "Ошибка: некорректный идентификатор группы.", show_alert=True)
                return
            user_id = call.from_user.id
            admins = db.get_admins(group_id)
            if user_id in admins:
                settings = db.get_group_settings(group_id)
                if not settings:
                    bot.answer_callback_query(call.id, "Ошибка: настройки группы не найдены.", show_alert=True)
                    return
                old_value = settings.get(setting, False)
                new_value = not old_value
                db.update_group_setting(group_id, setting, new_value)
                updated_settings = db.get_group_settings(group_id)
                if updated_settings.get(setting) != new_value:
                    bot.answer_callback_query(call.id, "Ошибка при обновлении настройки.", show_alert=True)
                    return
                bot.edit_message_text(
                    f"Настройки группы: {setting} изменено на {'Вкл' if new_value else 'Выкл'}",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=create_settings_menu(bot, group_id, user_id, db)
                )
                bot.answer_callback_query(call.id, f"Настройка {setting} изменена на {'✅' if new_value else '❌'}.")
            else:
                bot.answer_callback_query(call.id, "Вы не являетесь администратором этой группы!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "Ошибка: некорректный запрос.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('info:'))
    def handle_info_callback(call):
        parts = call.data.split(':')
        if len(parts) == 3:
            _, setting, group_id_str = parts
            try:
                group_id = int(group_id_str)
            except ValueError:
                bot.answer_callback_query(call.id, "Ошибка: некорректный идентификатор группы.", show_alert=True)
                return
            user_id = call.from_user.id
            admins = db.get_admins(group_id)
            if user_id not in admins:
                bot.answer_callback_query(call.id, "Вы не являетесь администратором этой группы!", show_alert=True)
                return
            descriptions = {
                'greeting_enabled': 'Включает/выключает автоматическое приветственное сообщение для новых участников группы.',
                'profanity_filter': 'Обнаруживает и удаляет сообщения с нецензурной лексикой, выдавая предупреждения.',
                'toxicity_filter': 'Обнаруживает токсичные сообщения с помощью ИИ, выдавая предупреждения.',
                'file_filter': 'Блокирует отправку потенциально опасных файлов (например, .exe, .bat) и наказывает отправителя.',
                'report_system': 'Добавляет команду /report. Вернитесь назад и нажмите на кнопку "Система жалоб", чтобы её настроить.',
                'link_filter': 'Обнаруживает и удаляет сообщения, содержащие ссылки, выдавая предупреждения.',
                'captcha_enabled': 'Требует от новых участников пройти капчу перед отправкой сообщений.'
            }
            description = descriptions.get(setting, 'Описание недоступно.')
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("← Назад", callback_data=f"settings_{group_id}"))
            bot.edit_message_text(
                f"ℹ️ Информация о настройке:\n\n{description}",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        else:
            bot.answer_callback_query(call.id, "Ошибка: некорректный запрос.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('info_rules_'))
    def handle_info_rules_callback(call):
        try:
            group_id = int(call.data.split('_')[2])
            user_id = call.from_user.id
            if user_id not in db.get_admins(group_id):
                bot.answer_callback_query(call.id, "Вы не являетесь администратором этой группы!", show_alert=True)
                return
            info_rules = db.get_info_rules(group_id)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("← Назад", callback_data=f"settings_{group_id}"))
            bot.edit_message_text(
                f"📜 Информация и правила:\n\n{info_rules}\n\nОтправьте новые правила, чтобы заменить текущие.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            waiting_for_rules[user_id] = {
                'group_id': group_id,
                'message_id': call.message.message_id,
                'chat_id': call.message.chat.id
            }
        except Exception as e:
            logger.error(f"Ошибка в info_rules callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('report_chat_'))
    def handle_report_chat_callback(call):
        try:
            group_id = int(call.data.split('_')[2])
            user_id = call.from_user.id
            if user_id not in db.get_admins(group_id):
                bot.answer_callback_query(call.id, "Вы не являетесь администратором этой группы!", show_alert=True)
                return
            log_chat_id = db.get_report_chat(group_id)
            if log_chat_id:
                bot.edit_message_text(
                    "⚙️ Настройки группы:",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=create_settings_menu(bot, group_id, user_id, db)
                )
                bot.answer_callback_query(call.id, "Вернулись к настройкам группы.")
                return
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("← Назад", callback_data=f"settings_{group_id}"))
            bot.edit_message_text(
                f"📢 Настройка чата для репортов:\n\n"
                f"1. Добавьте бота в группу, где будут логироваться жалобы.\n"
                f"2. Отправьте команду /setreportchat в том чате, куда хотите направить репорты.\n"
                f"Только вы можете выполнить эту команду для завершения настройки.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            waiting_for_report_chat[user_id] = {
                'group_id': group_id,
                'message_id': call.message.message_id,
                'chat_id': call.message.chat.id
            }
            logger.info(f"Ожидание команды /setreportchat для user_id {user_id}: {waiting_for_report_chat[user_id]}")
        except Exception as e:
            logger.error(f"Ошибка в report_chat callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('commands_'))
    def handle_commands_callback(call):
        group_id = int(call.data.split('_')[1])
        user_id = call.from_user.id
        bot.edit_message_text(
            "<b>Доступные команды:</b>\n"
            "/info - Показать информацию и правила группы\n"
            "/report [причина] - Отправить репорт на пользователя (ответ на сообщение)\n"
            "\n<b>Команды администратора:</b>\n"
            "/mute [время] - Замьютить пользователя (ответ на сообщение)\n"
            "/unmute - Размьютить пользователя (ответ на сообщение или @username)\n"
            "/ban - Забанить пользователя (ответ на сообщение)\n"
            "/reload - Обновить список администраторов группы",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("Назад", callback_data=f"settings_{group_id}")
            )
        )

    logger.info("Обработчики callback-запросов зарегистрированы успешно")