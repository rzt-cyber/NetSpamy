import sqlite3
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name="bot.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY
                )
            """)
            cursor.execute("PRAGMA table_info(groups)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'settings' not in columns:
                cursor.execute("""
                    ALTER TABLE groups ADD COLUMN settings TEXT DEFAULT '{"greeting_enabled": true, "profanity_filter": true, "auto_correction": true}'
                """)
                logger.info("Столбец settings добавлен в таблицу groups")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    chat_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    chat_id INTEGER,
                    user_id INTEGER,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mutes (
                    chat_id INTEGER,
                    user_id INTEGER,
                    unmute_time TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    reporter_id INTEGER,
                    reported_user_id INTEGER,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    user_id INTEGER PRIMARY KEY,
                    message_id INTEGER
                )
            """)
            conn.commit()
        logger.info("База данных инициализирована")

    def add_group(self, chat_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO groups (chat_id, settings) VALUES (?, ?)",
                (chat_id, '{"greeting_enabled": true, "profanity_filter": true, "auto_correction": true}')
            )
            conn.commit()
        logger.info(f"Группа {chat_id} добавлена в базу")

    def get_all_groups(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM groups")
            return [row[0] for row in cursor.fetchall()]

    def update_admins(self, chat_id, admins):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM admins WHERE chat_id = ?", (chat_id,))
            for admin_id in admins:
                cursor.execute(
                    "INSERT INTO admins (chat_id, user_id) VALUES (?, ?)",
                    (chat_id, admin_id)
                )
            conn.commit()
        logger.info(f"Список админов группы {chat_id} обновлен")

    def get_admins(self, chat_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id FROM admins WHERE chat_id = ?",
                (chat_id,)
            )
            return [row[0] for row in cursor.fetchall()]

    def get_group_settings(self, chat_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT settings FROM groups WHERE chat_id = ?",
                (chat_id,)
            )
            result = cursor.fetchone()
            if result:
                try:
                    settings = json.loads(result[0])
                    logger.info(f"Настройки для группы {chat_id}: {settings}")
                    return settings
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка декодирования JSON для группы {chat_id}: {e}")
                    return {}
            logger.warning(f"Настройки для группы {chat_id} не найдены")
            return {}

    def update_group_setting(self, chat_id, setting, value):
        try:
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT settings FROM groups WHERE chat_id = ?",
                    (chat_id,)
                )
                result = cursor.fetchone()
                if result:
                    try:
                        settings = json.loads(result[0])
                        logger.info(f"Текущие настройки для группы {chat_id}: {settings}")
                        settings[setting] = value
                        logger.info(f"Новые настройки для группы {chat_id}: {settings}")
                        cursor.execute(
                            "UPDATE groups SET settings = ? WHERE chat_id = ?",
                            (json.dumps(settings), chat_id)
                        )
                        conn.commit()
                        logger.info(f"Настройка {setting} для группы {chat_id} успешно обновлена: {value}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Ошибка декодирования JSON для группы {chat_id}: {e}")
                    except Exception as e:
                        logger.error(f"Ошибка при обновлении настройки {setting} для группы {chat_id}: {e}")
                else:
                    logger.warning(f"Группа {chat_id} не найдена в базе данных")
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при обновлении настройки для группы {chat_id}: {e}")

    def add_warning(self, chat_id, user_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO warnings (chat_id, user_id, count) VALUES (?, ?, 0)",
                (chat_id, user_id)
            )
            cursor.execute(
                "UPDATE warnings SET count = count + 1 WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            cursor.execute(
                "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            count = cursor.fetchone()[0]
            conn.commit()
            return count

    def reset_warnings(self, chat_id, user_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE warnings SET count = 0 WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            conn.commit()

    def add_mute(self, chat_id, user_id, unmute_time):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO mutes (chat_id, user_id, unmute_time) VALUES (?, ?, ?)",
                (chat_id, user_id, unmute_time)
            )
            conn.commit()

    def get_mute(self, chat_id, user_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT unmute_time FROM mutes WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            result = cursor.fetchone()
            return datetime.fromisoformat(result[0]) if result else None

    def remove_mute(self, chat_id, user_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM mutes WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            conn.commit()

    def add_report(self, chat_id, reporter_id, reported_user_id, reason):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO reports (chat_id, reporter_id, reported_user_id, reason) VALUES (?, ?, ?, ?)",
                (chat_id, reporter_id, reported_user_id, reason)
            )
            conn.commit()

    def save_welcome_message(self, user_id, message_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO welcome_messages (user_id, message_id) VALUES (?, ?)",
                (user_id, message_id)
            )
            conn.commit()
        logger.info(f"Приветственное сообщение для user_id {user_id} сохранено: message_id {message_id}")

    def get_welcome_message(self, user_id):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT message_id FROM welcome_messages WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else None