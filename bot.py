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

# Хранилище для временных данных
user_states = {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            check_date DATE,
            check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees (id)
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
    
    # Регистрируем пользователя как сотрудника
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO employees (full_name, telegram_id) VALUES (?, ?)', (full_name, user_id))
    conn.commit()
    conn.close()
    
    show_main_menu(message.chat.id, user_id)

def show_main_menu(chat_id, user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    keyboard.add(
        types.InlineKeyboardButton("📝 Отметить присутствие", callback_data="check_in"),
        types.InlineKeyboardButton("📊 Мой отчет", callback_data="my_report")
    )
    
    if is_admin(user_id):
        keyboard.add(types.InlineKeyboardButton("👥 Управление сотрудниками", callback_data="manage_employees"))
    
    bot.send_message(
        chat_id,
        "🏠 Главное меню:\nВыберите действие:",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    if call.data == "check_in":
        check_in(call)
    elif call.data == "my_report":
        my_report(call)
    elif call.data == "manage_employees":
        if is_admin(user_id):
            manage_employees(call)
        else:
            bot.answer_callback_query(call.id, "❌ У вас нет прав для этого действия")
    elif call.data == "add_employee":
        add_employee_menu(call)
    elif call.data == "view_employees":
        view_employees(call)
    elif call.data == "add_with_telegram":
        ask_telegram_id(call)
    elif call.data == "add_without_telegram":
        ask_employee_name(call)
    elif call.data == "back_to_menu":
        bot.delete_message(chat_id, call.message.message_id)
        show_main_menu(chat_id, user_id)
    elif call.data == "back_to_manage":
        manage_employees(call)

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
                "✅ Вы уже отметили присутствие сегодня!",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', (employee_id, today))
            conn.commit()
            bot.edit_message_text(
                "✅ Присутствие успешно отмечено!",
                call.message.chat.id,
                call.message.message_id
            )
    else:
        bot.edit_message_text(
            "❌ Вы не зарегистрированы как сотрудник!",
            call.message.chat.id,
            call.message.message_id
        )
    
    conn.close()

def my_report(call):
    user_id = call.from_user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, full_name, position FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if not employee:
        bot.edit_message_text(
            "❌ Вы не зарегистрированы как сотрудник!",
            call.message.chat.id,
            call.message.message_id
        )
        conn.close()
        return
    
    employee_id, full_name, position = employee
    
    cursor.execute('SELECT check_date, check_time FROM attendance WHERE employee_id = ? ORDER BY check_date DESC LIMIT 10', (employee_id,))
    attendance_records = cursor.fetchall()
    
    report_text = f"📊 Ваш отчет:\n\n👤 Имя: {full_name}\n"
    if position:
        report_text += f"💼 Должность: {position}\n"
    report_text += f"📈 Последние отметки ({len(attendance_records)}):\n\n"
    
    for record in attendance_records:
        report_text += f"✅ {record[0]} в {record[1][11:16]}\n"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    bot.edit_message_text(
        report_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )
    conn.close()

def manage_employees(call):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("➕ Добавить сотрудника", callback_data="add_employee"),
        types.InlineKeyboardButton("👥 Список сотрудников", callback_data="view_employees"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
    )
    
    bot.edit_message_text(
        "👥 Управление сотрудниками:\nВыберите действие:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

def add_employee_menu(call):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("📱 С привязкой к Telegram", callback_data="add_with_telegram"),
        types.InlineKeyboardButton("👤 Просто по имени", callback_data="add_without_telegram"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_manage")
    )
    
    bot.edit_message_text(
        "👥 Добавление сотрудника:\nВыберите тип добавления:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

def ask_telegram_id(call):
    user_states[call.from_user.id] = 'waiting_telegram_id'
    bot.edit_message_text(
        "Введите Telegram ID сотрудника:\n(Попросите сотрудника написать @userinfobot чтобы узнать ID)",
        call.message.chat.id,
        call.message.message_id
    )

def ask_employee_name(call):
    user_states[call.from_user.id] = 'waiting_employee_name'
    bot.edit_message_text(
        "Введите ФИО сотрудника:",
        call.message.chat.id,
        call.message.message_id
    )

def view_employees(call):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, full_name, position, telegram_id, is_active FROM employees ORDER BY is_active DESC, full_name')
    employees = cursor.fetchall()
    
    if not employees:
        text = "❌ Сотрудники не найдены"
    else:
        text = "👥 Список сотрудников:\n\n"
        for emp in employees:
            emp_id, full_name, position, telegram_id, is_active = emp
            status = "✅" if is_active else "❌"
            telegram_info = f"📱 ID: {telegram_id}" if telegram_id else "👤 Без Telegram"
            text += f"{status} {full_name}\n"
            if position:
                text += f"💼 {position}\n"
            text += f"{telegram_info}\n"
            text += f"🆔 ID в системе: {emp_id}\n\n"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_manage"))
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )
    conn.close()

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id in user_states:
        state = user_states[user_id]
        
        if state == 'waiting_telegram_id':
            try:
                telegram_id = int(message.text)
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                
                cursor.execute('SELECT * FROM employees WHERE telegram_id = ?', (telegram_id,))
                if cursor.fetchone():
                    bot.send_message(chat_id, "❌ Этот сотрудник уже добавлен!")
                else:
                    cursor.execute('INSERT INTO employees (full_name, telegram_id) VALUES (?, ?)', 
                                  (f"Сотрудник {telegram_id}", telegram_id))
                    conn.commit()
                    bot.send_message(chat_id, f"✅ Сотрудник с Telegram ID {telegram_id} добавлен!")
                
                conn.close()
                del user_states[user_id]
                show_main_menu(chat_id, user_id)
                
            except ValueError:
                bot.send_message(chat_id, "❌ Введите корректный ID (только цифры)")
        
        elif state == 'waiting_employee_name':
            employee_name = message.text
            user_states[user_id] = 'waiting_employee_position'
            user_states[f'{user_id}_name'] = employee_name
            bot.send_message(chat_id, f"Отлично! Теперь введите должность для {employee_name}:")
        
        elif state == 'waiting_employee_position':
            position = message.text
            employee_name = user_states.get(f'{user_id}_name')
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO employees (full_name, position) VALUES (?, ?)', (employee_name, position))
            conn.commit()
            conn.close()
            
            bot.send_message(chat_id, f"✅ Сотрудник добавлен!\n👤 Имя: {employee_name}\n💼 Должность: {position}")
            
            # Очищаем временные данные
            del user_states[user_id]
            if f'{user_id}_name' in user_states:
                del user_states[f'{user_id}_name']
            
            show_main_menu(chat_id, user_id)
    
    else:
        bot.send_message(chat_id, "Используйте кнопки меню для навигации 📱")

if __name__ == '__main__':
    init_db()
    logger.info("🤖 Бот запущен с полным функционалом!")
    bot.infinity_polling()
