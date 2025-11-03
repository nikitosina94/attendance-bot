import os
import logging
import sqlite3
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
DB_PATH = 'attendance.db'

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
    
    # Добавляем администратора
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

def start(update, context):
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name
    
    # Регистрируем пользователя
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO employees (full_name, telegram_id) VALUES (?, ?)', (full_name, user_id))
    conn.commit()
    conn.close()
    
    keyboard = [
        [InlineKeyboardButton("📝 Отметить присутствие", callback_data="check_in")],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("📊 Выгрузить отчет", callback_data="export_report")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        f"Привет, {full_name}! 👋\nБот для учета рабочего времени.",
        reply_markup=reply_markup
    )

def button_handler(update, context):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "check_in":
        check_in(query)
    elif data == "export_report" and is_admin(user_id):
        export_report(query)

def check_in(update):
    query = update
    user_id = query.from_user.id
    today = date.today().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем ID сотрудника
    cursor.execute('SELECT id FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if employee:
        employee_id = employee[0]
        
        # Проверяем, не отмечался ли сегодня
        cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND check_date = ?', (employee_id, today))
        
        if cursor.fetchone():
            query.edit_message_text("✅ Вы уже отметились сегодня!")
        else:
            cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', (employee_id, today))
            conn.commit()
            query.edit_message_text("✅ Присутствие отмечено!")
    else:
        query.edit_message_text("❌ Сотрудник не найден!")
    
    conn.close()

def export_report(update):
    query = update
    
    if not is_admin(query.from_user.id):
        query.edit_message_text("❌ Нет прав!")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Получаем данные для отчета
        cursor.execute('''
            SELECT e.full_name, a.check_date, a.check_time
            FROM attendance a 
            JOIN employees e ON a.employee_id = e.id
            ORDER BY a.check_date DESC
        ''')
        
        report_data = cursor.fetchall()
        
        if not report_data:
            query.edit_message_text("❌ Нет данных для отчета")
            return
        
        # Создаем текстовый отчет (вместо CSV/Excel)
        report_text = "📊 ОТЧЕТ ПО ПОСЕЩАЕМОСТИ\n\n"
        
        for row in report_data:
            full_name, check_date, check_time = row
            report_text += f"👤 {full_name}\n📅 {check_date}\n⏰ {check_time}\n{'='*30}\n"
        
        # Если отчет слишком длинный, разбиваем на части
        if len(report_text) > 4000:
            report_text = report_text[:4000] + "\n... (отчет обрезан)"
        
        query.edit_message_text(report_text)
        
    except Exception as e:
        logger.error(f"Ошибка при создании отчета: {e}")
        query.edit_message_text("❌ Ошибка при создании отчета")
    finally:
        conn.close()

def error(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return
    
    init_db()
    
    # Создаем Updater
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Обработчики команд
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик ошибок
    dp.add_error_handler(error)
    
    # Запускаем бота
    updater.start_polling()
    logger.info("🤖 Бот запущен!")
    
    # Работаем пока не остановят
    updater.idle()

if __name__ == '__main__':
    main()
