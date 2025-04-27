import time
import logging
from telebot import TeleBot
from config import BOT_TOKEN
from database import Database
from handlers.commands import register_commands
from handlers.events import register_events
from handlers.callbacks import register_callbacks

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = TeleBot(BOT_TOKEN)
db = Database()

if __name__ == '__main__':
    logger.info("Инициализация обработчиков команд")
    register_commands(bot, db)
    logger.info("Инициализация обработчиков событий")
    register_events(bot, db)
    logger.info("Инициализация обработчиков callback-запросов")
    register_callbacks(bot, db)
    while True:
        try:
            logger.info("Бот запущен!")
            bot.polling(none_stop=True, allowed_updates=["message", "chat_member", "my_chat_member", "callback_query"])
        except Exception as e:
            logger.error(f"Ошибка запуска: {e}")
            time.sleep(5)