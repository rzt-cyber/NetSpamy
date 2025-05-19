import time
import threading
from telebot import types
import logging
from database import Database

logger = logging.getLogger(__name__)

class VotingSystem:
    def __init__(self, bot, db: Database):
        self.bot = bot
        self.db = db

    def start_vote(self, chat_id, target_user, initiator_id, vote_type):
        """Запуск голосования"""
        # Проверка на существующее голосование
        if vote_type == "ban":
            existing = self.db.get_active_voteban(chat_id, target_user.id)
        else:
            existing = self.db.get_active_votemute(chat_id, target_user.id)
        
        if existing:
            self.bot.send_message(chat_id, "🚨 Голосование для этого пользователя уже идет!")
            return
        
        # Определение параметров голосования
        members_count = self.bot.get_chat_members_count(chat_id)
        if vote_type == "ban":
            votes_needed = max(3, members_count // 2)
        else:
            votes_needed = max(3, members_count // 10)

        end_time = int(time.time()) + 60

        # Сохранение в БД
        if vote_type == "ban":
            self.db.start_voteban(chat_id, target_user.id, initiator_id, votes_needed, end_time)
        else:
            self.db.start_votemute(chat_id, target_user.id, initiator_id, votes_needed, end_time)

        # Создание сообщения
        markup = types.InlineKeyboardMarkup()
        callback_data = f"vote_{vote_type}_{target_user.id}"
        markup.add(types.InlineKeyboardButton("✅ Проголосовать", callback_data=callback_data))

        msg = self.bot.send_message(
            chat_id,
            f"🚨 Голосование за {'бан' if vote_type == 'ban' else 'мут'} @{target_user.username}!\n"
            f"✅ Проголосовало: 0/{votes_needed}\n"
            f"⏳ Осталось: 60 сек.",
            reply_markup=markup
        )

        # Запуск таймеров
        saved_reply_markup = msg.reply_markup
        self._start_timer(
        chat_id, 
        msg.message_id, 
        end_time, 
        vote_type, 
        target_user.id, 
        saved_reply_markup  
        )

    def _start_timer(self, chat_id, message_id, end_time, vote_type, target_id, reply_markup):
        """Запуск обновления таймера"""
        self._update_timer(chat_id, message_id, end_time, vote_type, target_id, reply_markup)
        threading.Timer(60.0, self._check_vote_result, args=[chat_id, target_id, message_id, vote_type]).start()

    def _update_timer(self, chat_id, message_id, end_time, vote_type, target_id, reply_markup):
        """Обновление времени в сообщении"""
        remaining = end_time - int(time.time())
        if remaining <= 0:
            return

        try:
            # Получение данных из БД
            if vote_type == "ban":
                vote_data = self.db.get_active_voteban(chat_id, target_id)
            else:
                vote_data = self.db.get_active_votemute(chat_id, target_id)

            if vote_data:
                self.bot.edit_message_text(
                    f"🚨 Голосование за {'бан' if vote_type == 'ban' else 'мут'}!\n"
                    f"✅ Проголосовало: {vote_data['votes_current']}/{vote_data['votes_needed']}\n"
                    f"⏳ Осталось: {remaining} сек.",
                    chat_id,
                    message_id,
                    reply_markup=reply_markup
                )
                # Повторный запуск через 10 секунд
                threading.Timer(5.0, self._update_timer, 
                           args=[chat_id, message_id, end_time, vote_type, target_id, reply_markup]).start()
        except Exception as e:
            logger.error(f"Ошибка обновления таймера: {e}")

    def _check_vote_result(self, chat_id, target_id, message_id, vote_type):
        """Проверка результатов голосования"""
        try:
            # Получаем данные до закрытия голосования
            if vote_type == "ban":
                vote_data = self.db.get_active_voteban(chat_id, target_id)
                self.db.close_voteban(chat_id, target_id)
            else:
                vote_data = self.db.get_active_votemute(chat_id, target_id)
                self.db.close_votemute(chat_id, target_id)

            if vote_data:
                if vote_type == "ban":
                    self.db.close_voteban(chat_id, target_id)
                else:
                    self.db.close_votemute(chat_id, target_id)
            
            if not vote_data:  # Проверка на отсутствие данных
                self.bot.edit_message_text("❌ Голосование не найдено", chat_id, message_id)
                return

            if vote_data['votes_current'] >= vote_data['votes_needed']:
                # Применение наказания
                if vote_type == "ban":
                    self.bot.ban_chat_member(chat_id, target_id)
                    text = "⛔ Пользователь забанен!"
                else:
                    until_date = int(time.time()) + 86400  # Мут на 24 часа
                    self.bot.restrict_chat_member(
                        chat_id, target_id, 
                        until_date=until_date, 
                        can_send_messages=False
                    )
                    text = "🔇 Пользователь замьючен!"
            else:
                text = "❌ Голосование провалилось."

            self.bot.edit_message_text(text, chat_id, message_id)

        except Exception as e:
            logger.error(f"Ошибка завершения голосования: {e}", exc_info=True)

    def handle_vote(self, call):
        """Обработка голоса"""
        try:
            _, vote_type, target_id = call.data.split('_')
            target_id = int(target_id)
            chat_id = call.message.chat.id
            user_id = call.from_user.id

            if vote_type == "ban":
                success = self.db.add_vote(chat_id, target_id, user_id)
                vote_data = self.db.get_active_voteban(chat_id, target_id)
            else:
                success = self.db.add_vote_mute(chat_id, target_id, user_id)
                vote_data = self.db.get_active_votemute(chat_id, target_id)

            if success and vote_data:
                remaining = vote_data['end_time'] - int(time.time())
                self.bot.edit_message_text(
                    f"🚨 Голосование за {'бан' if vote_type == 'ban' else 'мут'}!\n"
                    f"✅ Проголосовало: {vote_data['votes_current']}/{vote_data['votes_needed']}\n"
                    f"⏳ Осталось: {remaining} сек.",
                    chat_id,
                    call.message.message_id,
                    reply_markup=call.message.reply_markup
                )
            else:
                self.bot.answer_callback_query(call.id, "❌ Вы уже голосовали!")
        except Exception as e:
            logger.error(f"Ошибка обработки голоса: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка!")