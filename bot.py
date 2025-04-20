import telebot
from telebot import types
from config import BOT_TOKEN
from message_filter import check_message

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup()
    button = types.InlineKeyboardButton(text="Добавить в группу", url="https://t.me/net_spamy_bot?startgroup=admin")
    markup.add(button)
    bot.send_message(message.chat.id, 
                     "Я бот-администратор групп, фильтрую сообщения пользователей.\n"
                     "Добавь меня в группу с помощью кнопки под сообщением.", 
                     reply_markup=markup)

@bot.message_handler(content_types=['new_chat_members'])
def new_member(message):
    for user in message.new_chat_members:
        if user.id == bot.get_me().id:
            bot.send_message(message.chat.id, "Я бот-администратор, буду следить за порядком")
            break

@bot.message_handler(content_types=['text'])
def handle_message(message):
    print(f"Получено сообщение: {message.text}")
    result = check_message(message.text)
    print(f"Предсказание: {result}")
    if result["is_toxic"]:
        bot.delete_message(message.chat.id, message.message_id)
        bot.send_message(message.chat.id, "⚠️ Сообщение удалено: нарушает правила.")
    else:
        pass  # сообщение остаётся

if __name__ == '__main__':
    print("Бот запущен!")
    bot.infinity_polling()
