import os
import sqlite3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin():
    DB_PATH = os.path.join(os.getcwd(), 'data', 'attendance.db')
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Создаем таблицы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT
        )
    ''')
    
    # Добавляем администратора
    admin_id = os.environ.get('ADMIN_ID')
    if admin_id:
        try:
            cursor.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (int(admin_id),))
            conn.commit()
            logger.info(f"✅ Администратор {admin_id} добавлен в базу!")
        except ValueError:
            logger.error("❌ ADMIN_ID должен быть числом")
    else:
        logger.warning("ℹ️ ADMIN_ID не установлен")
    
    conn.close()

if __name__ == '__main__':
    init_admin()
