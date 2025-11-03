import os
import logging
import sqlite3
import pandas as pd
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Состояния для ConversationHandler
WAITING_FOR_NAME, WAITING_FOR_POSITION = range(2)

# Путь к базе данных (для Render)
DB_PATH = '/etc/secrets/attendance.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица сотрудников
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            position TEXT,
            telegram_id INTEGER UNIQUE,
            is_active BOOLEAN DEFAULT TRUE,
            registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица посещаемости
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            check_date DATE,
            check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'present',
            FOREIGN KEY (employee_id) REFERENCES employees (id)
        )
    ''')
    
    # Таблица администраторов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT
        )
    ''')
    
    # Добавляем администратора при инициализации
    admin_id = os.environ.get('ADMIN_ID')
    if admin_id:
        cursor.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (int(admin_id),))
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# ... остальной код бота из предыдущих примеров ...
# (полный код слишком длинный, но он такой же как в railway версии)

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return
    
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ... обработчики команд ...
    
    logger.info("🤖 Бот запущен на Render!")
    application.run_polling()

if __name__ == '__main__':
    main()
