import os
import logging
import sqlite3
import pandas as pd
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        [InlineKeyboardButton("📊 Мой отчет", callback_data="my_report")],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("📋 Выгрузить отчет", callback_data="export_report")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Привет, {full_name}! 👋\nВыберите действие:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "check_in":
        await check_in(query)
    elif data == "my_report":
        await my_report(query)
    elif data == "export_report" and is_admin(user_id):
        await export_report(query)

async def check_in(query):
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
            await query.edit_message_text("✅ Вы уже отметились сегодня!")
        else:
            cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', (employee_id, today))
            conn.commit()
            await query.edit_message_text("✅ Присутствие отмечено!")
    else:
        await query.edit_message_text("❌ Сотрудник не найден!")
    
    conn.close()

async def my_report(query):
    user_id = query.from_user.id
    
    conn = sqlite3.connect(DB_PATH)
    
    # Получаем данные
    employee_data = pd.read_sql_query(
        'SELECT id, full_name FROM employees WHERE telegram_id = ?', 
        conn, params=(user_id,)
    )
    
    if not employee_data.empty:
        employee_id = employee_data.iloc[0]['id']
        full_name = employee_data.iloc[0]['full_name']
        
        attendance_data = pd.read_sql_query(
            'SELECT check_date FROM attendance WHERE employee_id = ? ORDER BY check_date DESC LIMIT 10', 
            conn, params=(employee_id,)
        )
        
        report_text = f"📊 Отчет: {full_name}\n\n"
        report_text += f"Всего отметок: {len(attendance_data)}\n\n"
        
        for _, row in attendance_data.iterrows():
            report_text += f"✅ {row['check_date']}\n"
    else:
        report_text = "❌ Данные не найдены"
    
    conn.close()
    await query.edit_message_text(report_text)

async def export_report(query):
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ Нет прав!")
        return
    
    conn = sqlite3.connect(DB_PATH)
    
    try:
        # Простой отчет без сложных операций pandas
        report_data = pd.read_sql_query('''
            SELECT e.full_name, a.check_date, a.check_time
            FROM attendance a 
            JOIN employees e ON a.employee_id = e.id
            ORDER BY a.check_date DESC
        ''', conn)
        
        if report_data.empty:
            await query.edit_message_text("❌ Нет данных для отчета")
            return
        
        # Сохраняем простой Excel
        filename = f"report_{datetime.now().strftime('%Y%m%d')}.xlsx"
        report_data.to_excel(filename, index=False)
        
        # Отправляем файл
        await query.message.reply_document(
            document=open(filename, 'rb'),
            caption="📊 Отчет по посещаемости"
        )
        
        await query.edit_message_text("✅ Отчет отправлен!")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await query.edit_message_text("❌ Ошибка создания отчета")
    finally:
        conn.close()

def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return
    
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🤖 Бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
