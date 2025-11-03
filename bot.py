import os
import logging
import sqlite3
from datetime import date
import telebot
from telebot import types

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
DB_PATH = 'attendance.db'

bot = telebot.TeleBot(BOT_TOKEN)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            telegram_id INTEGER UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            check_date DATE,
            check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER UNIQUE
        )
    ''')
    
    admin_id = os.environ.get('ADMIN_ID')
    if admin_id:
        cursor.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (int(admin_id),))
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    full_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO employees (full_name, telegram_id) VALUES (?, ?)', (full_name, user_id))
    conn.commit()
    conn.close()
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📝 Отметить присутствие", callback_data="check_in"))
    
    if is_admin(user_id):
        keyboard.add(types.InlineKeyboardButton("📊 Выгрузить отчет", callback_data="export_report"))
    
    bot.send_message(
        message.chat.id,
        f"Привет, {full_name}! 👋\nБот для учета рабочего времени.",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    
    if call.data == "check_in":
        check_in(call)
    elif call.data == "export_report" and is_admin(user_id):
        export_report(call)

def check_in(call):
    user_id = call.from_user.id
    today = date.today().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if employee:
        employee_id = employee[0]
        
        cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND check_date = ?', (employee_id, today))
        
        if cursor.fetchone():
            bot.edit_message_text(
                "✅ Вы уже отметились сегодня!",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', (employee_id, today))
            conn.commit()
            bot.edit_message_text(
                "✅ Присутствие отмечено!",
                call.message.chat.id,
                call.message.message_id
            )
    else:
        bot.edit_message_text(
            "❌ Сотрудник не найден!",
            call.message.chat.id,
            call.message.message_id
        )
    
    conn.close()

def export_report(call):
    if not is_admin(call.from_user.id):
        bot.edit_message_text(
            "❌ Нет прав!",
            call.message.chat.id,
            call.message.message_id
        )
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT e.full_name, a.check_date, a.check_time
            FROM attendance a 
            JOIN employees e ON a.employee_id = e.id
            ORDER BY a.check_date DESC
        ''')
        
        report_data = cursor.fetchall()
        
        if not report_data:
            bot.edit_message_text(
                "❌ Нет данных для отчета",
                call.message.chat.id,
                call.message.message_id
            )
            return
        
        report_text = "📊 ОТЧЕТ ПО ПОСЕЩАЕМОСТИ\n\n"
        
        for row in report_data:
            full_name, check_date, check_time = row
            report_text += f"👤 {full_name}\n📅 {check_date}\n⏰ {check_time}\n{'='*30}\n"
        
        if len(report_text) > 4000:
            report_text = report_text[:4000] + "\n... (отчет обрезан)"
        
        bot.edit_message_text(
            report_text,
            call.message.chat.id,
            call.message.message_id
        )
        
    except Exception as e:
        logger.error(f"Ошибка при создании отчета: {e}")
        bot.edit_message_text(
            "❌ Ошибка при создании отчета",
            call.message.chat.id,
            call.message.message_id
        )
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()
    logger.info("🤖 Бот запущен!")
    bot.infinity_polling()
