import sqlite3
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name="bot.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.init_db()
        logger.info("Database connection initialized")

    def init_db(self):
        """Инициализация всех таблиц в базе данных"""
        try:
            # Создание таблицы groups
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY,
                    settings TEXT DEFAULT '{"greeting_enabled": true, "profanity_filter": true, "auto_correction": true}',
                    work_start INTEGER DEFAULT 0,  
                    work_end INTEGER DEFAULT 1440, 
                    timezone TEXT DEFAULT 'UTC',
                    is_closed BOOLEAN DEFAULT FALSE
                )
            """)

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
                CREATE TABLE IF NOT EXISTS mutes (
                    chat_id INTEGER,
                    user_id INTEGER,
                    unmute_time TIMESTAMP,
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
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    user_id INTEGER PRIMARY KEY,
                    message_id INTEGER
                )
            """)

            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS votebans (
                    chat_id INTEGER,
                    target_user_id INTEGER,
                    initiator_user_id INTEGER,
                    votes_needed INTEGER,
                    votes_current INTEGER DEFAULT 0,
                    voted_user_ids TEXT DEFAULT '[]',
                    end_time INTEGER,
                    is_active BOOLEAN DEFAULT TRUE,
                    PRIMARY KEY (chat_id, target_user_id)
                )
            ''')

            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS votemutes (
                    chat_id INTEGER,
                    target_user_id INTEGER,
                    initiator_user_id INTEGER,
                    votes_needed INTEGER,
                    votes_current INTEGER DEFAULT 0,
                    voted_user_ids TEXT DEFAULT '[]',
                    end_time INTEGER,
                    is_active BOOLEAN DEFAULT TRUE,
                    PRIMARY KEY (chat_id, target_user_id)
                )
            ''')
            
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS rules (
                    chat_id INTEGER PRIMARY KEY,
                    text TEXT DEFAULT '📜 Правила чата не установлены.'
                )
            ''')
            
            self.conn.commit()
            logger.info("All tables initialized successfully")

        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def __del__(self):
        """Закрытие соединения при уничтожении объекта"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    # Groups
    def add_group(self, chat_id):
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO groups (chat_id) VALUES (?)",
                (chat_id,)
            )
            self.conn.commit()
            logger.info(f"Группа {chat_id} добавлена в базу")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при добавлении группы: {e}")

    def get_all_groups(self):
        try:
            self.cursor.execute("SELECT chat_id FROM groups")
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении групп: {e}")
            return []

    # Admins
    def update_admins(self, chat_id, admins):
        try:
            self.cursor.execute("DELETE FROM admins WHERE chat_id = ?", (chat_id,))
            for admin_id in admins:
                self.cursor.execute(
                    "INSERT INTO admins (chat_id, user_id) VALUES (?, ?)",
                    (chat_id, admin_id)
                )
            self.conn.commit()
            logger.info(f"Обновлены данные администраторов чата {chat_id}")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при обновлении администраторов: {e}")

    def get_admins(self, chat_id):
        try:
            self.cursor.execute(
                "SELECT user_id FROM admins WHERE chat_id = ?",
                (chat_id,)
            )
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении доступа к администраторам: {e}")
            return []

    # Settings
    def get_group_settings(self, chat_id):
        try:
            self.cursor.execute(
                "SELECT settings FROM groups WHERE chat_id = ?",
                (chat_id,)
            )
            result = self.cursor.fetchone()
            if result:
                return json.loads(result[0])
            return {}
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении настроек: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка декодирования JSON: {e}")
            return {}

    def update_group_setting(self, chat_id, setting, value):
        try:
            settings = self.get_group_settings(chat_id)
            settings[setting] = value
            self.cursor.execute(
                "UPDATE groups SET settings = ? WHERE chat_id = ?",
                (json.dumps(settings), chat_id))
            self.conn.commit()
            logger.info(f"Обновлены настройки для {chat_id}")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при обновлении настроек: {e}")

    # Warnings
    def add_warning(self, chat_id, user_id):
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO warnings (chat_id, user_id) VALUES (?, ?)",
                (chat_id, user_id)
            )
            self.cursor.execute(
                "UPDATE warnings SET count = count + 1 WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            self.cursor.execute(
                "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            count = self.cursor.fetchone()[0]
            self.conn.commit()
            return count
        except sqlite3.Error as e:
            logger.error(f"Предупреждение об ошибке при добавлении: {e}")
            return 0

    def reset_warnings(self, chat_id, user_id):
        try:
            self.cursor.execute(
                "UPDATE warnings SET count = 0 WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Предупреждения об ошибках при сбросе настроек: {e}")

    # Mutes
    def add_mute(self, chat_id, user_id, unmute_time):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO mutes (chat_id, user_id, unmute_time) VALUES (?, ?, ?)",
                (chat_id, user_id, unmute_time)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Ошибка при выдачи мута: {e}")

    def get_mute(self, chat_id, user_id):
        try:
            self.cursor.execute(
                "SELECT unmute_time FROM mutes WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            result = self.cursor.fetchone()
            return datetime.fromisoformat(result[0]) if result else None
        except sqlite3.Error as e:
            logger.error(f"Error getting mute: {e}")
            return None

    def remove_mute(self, chat_id, user_id):
        try:
            self.cursor.execute(
                "DELETE FROM mutes WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error removing mute: {e}")

    # Reports
    def add_report(self, chat_id, reporter_id, reported_user_id, reason):
        try:
            self.cursor.execute(
                "INSERT INTO reports (chat_id, reporter_id, reported_user_id, reason) VALUES (?, ?, ?, ?)",
                (chat_id, reporter_id, reported_user_id, reason)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error adding report: {e}")

    # Welcome messages
    def save_welcome_message(self, user_id, message_id):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO welcome_messages (user_id, message_id) VALUES (?, ?)",
                (user_id, message_id)
            )
            self.conn.commit()
            logger.info(f"Welcome message saved for {user_id}")
        except sqlite3.Error as e:
            logger.error(f"Error saving welcome message: {e}")

    def get_welcome_message(self, user_id):
        try:
            self.cursor.execute(
                "SELECT message_id FROM welcome_messages WHERE user_id = ?",
                (user_id,)
            )
            result = self.cursor.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            logger.error(f"Error getting welcome message: {e}")
            return None

    # Voteban system
    def start_voteban(self, chat_id, target_user_id, initiator_user_id, votes_needed, end_time):
        try:
            self.cursor.execute('''
                INSERT INTO votebans (
                    chat_id, target_user_id, initiator_user_id, votes_needed, end_time
                ) VALUES (?, ?, ?, ?, ?)
            ''', (chat_id, target_user_id, initiator_user_id, votes_needed, end_time))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error starting voteban: {e}")
            return False

    def get_active_voteban(self, chat_id, target_user_id):
        try:
            self.cursor.execute('''
                SELECT * FROM votebans 
                WHERE chat_id = ? AND target_user_id = ? AND is_active = 1
            ''', (chat_id, target_user_id))
            result = self.cursor.fetchone()
            logger.debug(f"Voteban data: {dict(result) if result else None}")  # Логируем
            return result
        except sqlite3.Error as e:
            logger.error(f"Error getting active voteban: {e}")
            return None

    def add_vote(self, chat_id, target_user_id, user_id):
        try:
            voteban = self.get_active_voteban(chat_id, target_user_id)
            if not voteban:
                return False

            voted_users = json.loads(voteban['voted_user_ids'])
            if user_id in voted_users:
                return False

            voted_users.append(user_id)
            self.cursor.execute('''
                UPDATE votebans 
                SET votes_current = votes_current + 1, 
                    voted_user_ids = ?
                WHERE chat_id = ? AND target_user_id = ?
            ''', (json.dumps(voted_users), chat_id, target_user_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error adding vote: {e}")
            return False

    def close_voteban(self, chat_id, target_user_id):
        try:
            self.cursor.execute('''
                DELETE FROM votebans 
                WHERE chat_id = ? AND target_user_id = ?
            ''', (chat_id, target_user_id))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error deleting voteban: {e}")

    # Votemute system
    def start_votemute(self, chat_id, target_user_id, initiator_user_id, votes_needed, end_time):
        try:
            self.cursor.execute('''
                INSERT INTO votemutes (
                    chat_id, target_user_id, initiator_user_id, votes_needed, end_time
                ) VALUES (?, ?, ?, ?, ?)
            ''', (chat_id, target_user_id, initiator_user_id, votes_needed, end_time))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error starting votemute: {e}")
            return False

    def get_active_votemute(self, chat_id, target_user_id):
        try:
            self.cursor.execute('''
                SELECT * FROM votemutes 
                WHERE chat_id = ? AND target_user_id = ? AND is_active = 1
            ''', (chat_id, target_user_id))
            result = self.cursor.fetchone()
            logger.debug(f"Active votemute data: {dict(result) if result else None}")
            return result
        except sqlite3.Error as e:
            logger.error(f"Error getting active votemute: {e}")
            return None

    def add_vote_mute(self, chat_id, target_user_id, user_id):
        try:
            votemute = self.get_active_votemute(chat_id, target_user_id)
            if not votemute:
                return False

            voted_users = json.loads(votemute['voted_user_ids'])
            if user_id in voted_users:
                return False

            voted_users.append(user_id)
            self.cursor.execute('''
                UPDATE votemutes 
                SET votes_current = votes_current + 1, 
                    voted_user_ids = ?
                WHERE chat_id = ? AND target_user_id = ?
            ''', (json.dumps(voted_users), chat_id, target_user_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error adding mute vote: {e}")
            return False

    def close_votemute(self, chat_id, target_user_id):
        try:
            self.cursor.execute('''
                DELETE FROM votemutes 
                WHERE chat_id = ? AND target_user_id = ?
            ''', (chat_id, target_user_id))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error deleting votemute: {e}")
            
    def set_rules(self, chat_id, text):
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO rules (chat_id, text) VALUES (?, ?)",
                (chat_id, text)
            )
            self.conn.commit()
            logger.info(f"Правила чата {chat_id} обновлены")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения правил: {e}")
            return False

    def get_rules(self, chat_id):
        """Получение правил чата"""
        try:
            self.cursor.execute(
                "SELECT text FROM rules WHERE chat_id = ?",
                (chat_id,)
            )
            result = self.cursor.fetchone()
            return result['text'] if result else "📜 Правила чата не установлены."
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения правил: {e}")
            return None
        
    # Режим работы чата
    def update_work_hours(self, chat_id, work_start, work_end, timezone):
        try:
            self.cursor.execute(
                "UPDATE groups SET work_start = ?, work_end = ?, timezone = ? WHERE chat_id = ?",
                (work_start, work_end, timezone, chat_id)
            )
            self.conn.commit()
            
            # Импортируем здесь, чтобы избежать циклических импортов
            from main import bot  # Получаем экземпляр бота
            from handlers.events import handle_chat_status
            # Вызываем с force_notification=True для отправки уведомления
            handle_chat_status(bot, self, chat_id, force_notification=True)
            
        except Exception as e:
            logger.error(f"Ошибка обновления режима работы: {e}")

    def get_work_hours(self, chat_id):
        
        self.cursor.execute(
            "SELECT work_start, work_end, timezone FROM groups WHERE chat_id = ?",
            (chat_id,)
        )
        return self.cursor.fetchone()
    
    def set_chat_closed(self, chat_id: int, is_closed: bool):
        try:
            self.cursor.execute(
                "UPDATE groups SET is_closed = ? WHERE chat_id = ?",
                (is_closed, chat_id)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Ошибка обновления статуса чата: {e}")

    def is_chat_closed(self, chat_id: int) -> bool:
        try:
            self.cursor.execute(
                "SELECT is_closed FROM groups WHERE chat_id = ?",
                (chat_id,)
            )
            result = self.cursor.fetchone()
            return result['is_closed'] if result else False
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения статуса чата: {e}")
            return False