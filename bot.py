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

def create_main_menu(user_id):
    """Создает основное меню"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    buttons = [
        "📝 Отметить присутствие",
        "📊 Мой отчет", 
        "ℹ️ Помощь"
    ]
    
    if is_admin(user_id):
        buttons.append("👥 Управление")
    
    keyboard.add(*buttons)
    return keyboard

def create_management_menu():
    """Создает меню управления"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "➕ Добавить сотрудника",
        "👥 Список сотрудников", 
        "🔙 Главное меню"
    ]
    keyboard.add(*buttons)
    return keyboard

def create_add_employee_menu():
    """Создает меню добавления сотрудника"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "📱 С Telegram",
        "👤 Без Telegram",
        "🔙 Назад"
    ]
    keyboard.add(*buttons)
    return keyboard

def create_back_menu():
    """Создает меню с кнопкой Назад"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("🔙 Назад")
    return keyboard

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
    menu_text = "🏠 ГЛАВНОЕ МЕНЮ\n\nВыберите действие:"
    bot.send_message(chat_id, menu_text, reply_markup=create_main_menu(user_id))

def show_management_menu(chat_id):
    menu_text = "👥 УПРАВЛЕНИЕ СОТРУДНИКАМИ\n\nВыберите действие:"
    bot.send_message(chat_id, menu_text, reply_markup=create_management_menu())

def show_add_employee_menu(chat_id):
    menu_text = "➕ ДОБАВЛЕНИЕ СОТРУДНИКА\n\nВыберите тип добавления:"
    bot.send_message(chat_id, menu_text, reply_markup=create_add_employee_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    
    # Если пользователь в процессе добавления сотрудника
    if user_id in user_states:
        handle_employee_creation(message)
        return
    
    # Обработка основного меню
    if text == "📝 Отметить присутствие":
        check_in(message)
    
    elif text == "📊 Мой отчет":
        my_report(message)
    
    elif text == "👥 Управление":
        if is_admin(user_id):
            show_management_menu(chat_id)
        else:
            bot.send_message(chat_id, "❌ У вас нет прав для управления сотрудниками")
            show_main_menu(chat_id, user_id)
    
    elif text == "ℹ️ Помощь":
        show_help(message)
    
    # Обработка меню управления
    elif text == "➕ Добавить сотрудника":
        show_add_employee_menu(chat_id)
    
    elif text == "👥 Список сотрудников":
        view_employees(message)
    
    elif text == "🔙 Главное меню":
        show_main_menu(chat_id, user_id)
    
    # Обработка меню добавления сотрудника
    elif text == "📱 С Telegram":
        user_states[user_id] = 'waiting_telegram_id'
        bot.send_message(chat_id, 
            "Введите Telegram ID сотрудника:\n\n"
            "📋 Как узнать ID:\n"
            "1. Попросите сотрудника написать @userinfobot\n"
            "2. Бот покажет его ID\n"
            "3. Пришлите сюда цифры ID", 
            reply_markup=create_back_menu()
        )
    
    elif text == "👤 Без Telegram":
        user_states[user_id] = 'waiting_employee_name'
        bot.send_message(chat_id, 
            "Введите ФИО сотрудника:", 
            reply_markup=create_back_menu()
        )
    
    elif text == "🔙 Назад":
        if user_id in user_states:
            del user_states[user_id]
        show_management_menu(chat_id)
    
    else:
        show_main_menu(chat_id, user_id)

def handle_employee_creation(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states[user_id]
    
    if text == "🔙 Назад":
        del user_states[user_id]
        show_add_employee_menu(chat_id)
        return
    
    if state == 'waiting_telegram_id':
        try:
            telegram_id = int(text)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM employees WHERE telegram_id = ?', (telegram_id,))
            if cursor.fetchone():
                bot.send_message(chat_id, "❌ Этот сотрудник уже добавлен!")
            else:
                cursor.execute('INSERT INTO employees (full_name, telegram_id) VALUES (?, ?)', 
                              (f"Сотрудник {telegram_id}", telegram_id))
                conn.commit()
                bot.send_message(chat_id, 
                    f"✅ Сотрудник добавлен!\n"
                    f"📱 Telegram ID: {telegram_id}\n"
                    f"👤 Имя: Сотрудник {telegram_id}\n\n"
                    f"📝 Можно изменить имя через управление сотрудниками")
            
            conn.close()
            del user_states[user_id]
            show_management_menu(chat_id)
            
        except ValueError:
            bot.send_message(chat_id, "❌ Введите корректный ID (только цифры)")
    
    elif state == 'waiting_employee_name':
        employee_name = text
        user_states[user_id] = 'waiting_employee_position'
        user_states[f'{user_id}_name'] = employee_name
        bot.send_message(chat_id, f"Отлично! Теперь введите должность для {employee_name}:")
    
    elif state == 'waiting_employee_position':
        position = text
        employee_name = user_states.get(f'{user_id}_name')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO employees (full_name, position) VALUES (?, ?)', (employee_name, position))
        conn.commit()
        conn.close()
        
        bot.send_message(chat_id, 
            f"✅ Сотрудник добавлен!\n"
            f"👤 Имя: {employee_name}\n"
            f"💼 Должность: {position}\n\n"
            f"📋 Теперь вы можете отмечать присутствие за этого сотрудника")
        
        # Очищаем временные данные
        del user_states[user_id]
        if f'{user_id}_name' in user_states:
            del user_states[f'{user_id}_name']
        
        show_management_menu(chat_id)

def check_in(message):
    user_id = message.from_user.id
    today = date.today().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if employee:
        employee_id = employee[0]
        
        cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND check_date = ?', (employee_id, today))
        
        if cursor.fetchone():
            bot.send_message(message.chat.id, "✅ Вы уже отметили присутствие сегодня!")
        else:
            cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', (employee_id, today))
            conn.commit()
            bot.send_message(message.chat.id, "✅ Присутствие успешно отмечено!")
    else:
        bot.send_message(message.chat.id, "❌ Вы не зарегистрированы как сотрудник!")
    
    conn.close()

def my_report(message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, full_name, position FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if not employee:
        bot.send_message(message.chat.id, "❌ Вы не зарегистрированы как сотрудник!")
        conn.close()
        return
    
    employee_id, full_name, position = employee
    
    cursor.execute('SELECT check_date, check_time FROM attendance WHERE employee_id = ? ORDER BY check_date DESC LIMIT 10', (employee_id,))
    attendance_records = cursor.fetchall()
    
    report_text = f"📊 ВАШ ОТЧЕТ\n\n👤 Имя: {full_name}\n"
    if position:
        report_text += f"💼 Должность: {position}\n"
    
    report_text += f"📈 Последние отметки ({len(attendance_records)}):\n\n"
    
    for record in attendance_records:
        report_text += f"✅ {record[0]} в {record[1][11:16]}\n"
    
    if not attendance_records:
        report_text += "Пока нет отметок присутствия\n"
    
    bot.send_message(message.chat.id, report_text)
    conn.close()

def view_employees(message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, full_name, position, telegram_id, is_active FROM employees ORDER BY is_active DESC, full_name')
    employees = cursor.fetchall()
    
    if not employees:
        text = "❌ Сотрудники не найдены"
    else:
        text = "👥 СПИСОК СОТРУДНИКОВ\n\n"
        for emp in employees:
            emp_id, full_name, position, telegram_id, is_active = emp
            status = "✅" if is_active else "❌"
            telegram_info = f"📱 ID: {telegram_id}" if telegram_id else "👤 Без Telegram"
            text += f"{status} {full_name}\n"
            if position:
                text += f"💼 {position}\n"
            text += f"{telegram_info}\n"
            text += f"🆔 ID в системе: {emp_id}\n\n"
    
    bot.send_message(message.chat.id, text)
    conn.close()

def show_help(message):
    help_text = """ℹ️ ПОМОЩЬ

📝 ОСНОВНЫЕ ФУНКЦИИ:
• Отметить присутствие - ежедневная отметка
• Мой отчет - просмотр вашей статистики
• Управление - для администраторов

👥 ДЛЯ АДМИНИСТРАТОРОВ:
• Добавление сотрудников с Telegram или по имени
• Просмотр списка всех сотрудников
• Отслеживание посещаемости

Просто выбирайте нужные пункты из меню!"""
    
    bot.send_message(message.chat.id, help_text)

if __name__ == '__main__':
    init_db()
    logger.info("🤖 Бот запущен с выпадающим меню!")
    bot.infinity_polling()
