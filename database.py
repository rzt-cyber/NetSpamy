import sqlite3
import json
import logging
from datetime import datetime
from config import BOT_INVITE_URL, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name="bot.db"):
        """Инициализация соединения с базой данных."""
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.init_db()
        logger.info("Database connection initialized")

    def init_db(self):
        """Инициализация всех таблиц в базе данных."""
        try:
            # Создаем таблицу groups с валидным JSON для DEFAULT_SETTINGS
            default_settings_json = json.dumps(DEFAULT_SETTINGS)
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY,
                    settings TEXT DEFAULT '{}',
                    info_rules TEXT DEFAULT 'Здравствуйте, пока!'
                )
                """.format(default_settings_json.replace('"', '\\"'))
            )

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    chat_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    chat_id INTEGER,
                    user_id INTEGER,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    reporter_id INTEGER,
                    reported_user_id INTEGER,
                    reason TEXT,
                    message_id INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    user_id INTEGER PRIMARY KEY,
                    message_id INTEGER
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS report_chats (
                    chat_id INTEGER PRIMARY KEY,
                    log_chat_id INTEGER
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS captcha_status (
                    chat_id INTEGER,
                    user_id INTEGER,
                    passed INTEGER DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            self.conn.commit()
            logger.info("All tables initialized successfully")

        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def __del__(self):
        """Закрытие соединения с базой данных."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    def add_chat_member(self, chat_id, user_id):
        """Добавление участника чата."""
        try:
            self.cursor.execute("INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
            self.cursor.execute("INSERT OR IGNORE INTO captcha_status (chat_id, user_id, passed) VALUES (?, ?, 0)", (chat_id, user_id))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error adding chat member: {e}")

    def remove_chat_member(self, chat_id, user_id):
        """Удаление участника чата."""
        try:
            self.cursor.execute("DELETE FROM chat_members WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            self.cursor.execute("DELETE FROM captcha_status WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error removing chat member: {e}")

    def get_chat_members(self, chat_id):
        """Получение списка участников чата."""
        try:
            self.cursor.execute("SELECT user_id FROM chat_members WHERE chat_id = ?", (chat_id,))
            return [row['user_id'] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error getting chat members: {e}")
            return []

    def add_group(self, chat_id):
        """Добавление новой группы."""
        try:
            self.cursor.execute("INSERT OR IGNORE INTO groups (chat_id, settings) VALUES (?, ?)", (chat_id, json.dumps(DEFAULT_SETTINGS)))
            self.conn.commit()
            logger.info(f"Группа {chat_id} добавлена с настройками: {DEFAULT_SETTINGS}")
        except sqlite3.Error as e:
            logger.error(f"Error adding group {chat_id}: {e}")

    def mark_existing_members(self, chat_id, bot):
        """Помечает всех текущих участников группы как прошедших капчу."""
        try:
            chat_members = bot.get_chat_administrators(chat_id)
            user_ids = [member.user.id for member in chat_members]
            for user_id in user_ids:
                self.cursor.execute("""
                    INSERT OR REPLACE INTO chat_members (chat_id, user_id)
                    VALUES (?, ?)
                """, (chat_id, user_id))
                self.cursor.execute("""
                    INSERT OR REPLACE INTO captcha_status (chat_id, user_id, passed)
                    VALUES (?, ?, 1)
                """, (chat_id, user_id))
            self.conn.commit()
            logger.info(f"Все текущие участники группы {chat_id} помечены как прошедшие капчу")
        except Exception as e:
            logger.error(f"Ошибка при пометке текущих участников группы {chat_id}: {e}")

    def get_all_groups(self):
        """Получение списка всех групп."""
        self.cursor.execute("SELECT chat_id FROM groups")
        return [row['chat_id'] for row in self.cursor.fetchall()]

    def update_admins(self, chat_id, admin_ids):
        """Обновление списка администраторов."""
        self.cursor.execute("DELETE FROM admins WHERE chat_id = ?", (chat_id,))
        for admin_id in admin_ids:
            self.cursor.execute("INSERT OR IGNORE INTO admins (chat_id, user_id) VALUES (?, ?)", (chat_id, admin_id))
        self.conn.commit()

    def get_admins(self, chat_id):
        """Получение списка администраторов группы."""
        self.cursor.execute("SELECT user_id FROM admins WHERE chat_id = ?", (chat_id,))
        return [row['user_id'] for row in self.cursor.fetchall()]

    def add_warning(self, chat_id, user_id):
        """Добавление предупреждения пользователю."""
        self.cursor.execute("""
            INSERT OR REPLACE INTO warnings (chat_id, user_id, count)
            VALUES (?, ?, COALESCE((SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?), 0) + 1)
        """, (chat_id, user_id, chat_id, user_id))
        self.conn.commit()
        self.cursor.execute("SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return self.cursor.fetchone()['count']

    def reset_warnings(self, chat_id, user_id):
        """Сброс предупреждений пользователя."""
        self.cursor.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        self.conn.commit()

    def add_report(self, chat_id, reporter_id, reported_user_id, reason, message_id):
        """Добавление репорта."""
        self.cursor.execute("""
            INSERT INTO reports (chat_id, reporter_id, reported_user_id, reason, message_id)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, reporter_id, reported_user_id, reason, message_id))
        self.conn.commit()

    def get_group_settings(self, chat_id):
        """Получение настроек группы."""
        self.cursor.execute("SELECT settings FROM groups WHERE chat_id = ?", (chat_id,))
        row = self.cursor.fetchone()
        return json.loads(row['settings']) if row else DEFAULT_SETTINGS

    def update_group_setting(self, chat_id, setting, value):
        """Обновление настройки группы."""
        settings = self.get_group_settings(chat_id)
        settings[setting] = value
        self.cursor.execute("UPDATE groups SET settings = ? WHERE chat_id = ?", (json.dumps(settings), chat_id))
        self.conn.commit()

    def get_info_rules(self, chat_id):
        """Получение правил группы."""
        self.cursor.execute("SELECT info_rules FROM groups WHERE chat_id = ?", (chat_id,))
        row = self.cursor.fetchone()
        return row['info_rules'] if row else "Здравствуйте, пока!"

    def update_info_rules(self, chat_id, new_rules):
        """Обновление правил группы."""
        self.cursor.execute("UPDATE groups SET info_rules = ? WHERE chat_id = ?", (new_rules, chat_id))
        self.conn.commit()

    def save_welcome_message(self, user_id, message_id):
        """Сохранение приветственного сообщения."""
        self.cursor.execute("""
            INSERT OR REPLACE INTO welcome_messages (user_id, message_id)
            VALUES (?, ?)
        """, (user_id, message_id))
        self.conn.commit()

    def get_welcome_message(self, user_id):
        """Получение приветственного сообщения."""
        self.cursor.execute("SELECT message_id FROM welcome_messages WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row['message_id'] if row else None

    def set_report_chat(self, chat_id, log_chat_id):
        """Установка чата для репортов."""
        self.cursor.execute("""
            INSERT OR REPLACE INTO report_chats (chat_id, log_chat_id)
            VALUES (?, ?)
        """, (chat_id, log_chat_id))
        self.conn.commit()

    def get_report_chat(self, chat_id):
        """Получение чата для репортов."""
        self.cursor.execute("SELECT log_chat_id FROM report_chats WHERE chat_id = ?", (chat_id,))
        row = self.cursor.fetchone()
        return row['log_chat_id'] if row else None

    def get_bot_invite_url(self):
        """Получение URL для приглашения бота."""
        return BOT_INVITE_URL

    def set_captcha_passed(self, chat_id, user_id):
        """Установка статуса прохождения капчи."""
        try:
            self.cursor.execute("""
                INSERT OR REPLACE INTO captcha_status (chat_id, user_id, passed)
                VALUES (?, ?, 1)
            """, (chat_id, user_id))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error setting captcha status: {e}")

    def has_passed_captcha(self, chat_id, user_id):
        """Проверка статуса прохождения капчи."""
        try:
            self.cursor.execute("SELECT passed FROM captcha_status WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            row = self.cursor.fetchone()
            return row['passed'] == 1 if row else False
        except sqlite3.Error as e:
            logger.error(f"Error checking captcha status: {e}")
            return False