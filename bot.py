import os
import logging
import sqlite3
from datetime import date, datetime, timedelta
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
            is_active BOOLEAN DEFAULT TRUE,
            registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            check_date DATE,
            marked_by TEXT DEFAULT 'admin',
            marked_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

def create_main_menu():
    """Создает основное меню"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "👥 Сотрудники",
        "✅ Отметить присутствие", 
        "📊 Отчеты",
        "📅 Отметить за прошлую дату",
        "ℹ️ Помощь"
    ]
    keyboard.add(*buttons)
    return keyboard

def create_employees_menu():
    """Создает меню сотрудников"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "➕ Добавить сотрудника",
        "👥 Список сотрудников",
        "✏️ Редактировать сотрудника",
        "🔙 Главное меню"
    ]
    keyboard.add(*buttons)
    return keyboard

def create_reports_menu():
    """Создает меню отчетов"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "📈 Общий отчет",
        "👤 Отчет по сотруднику",
        "📅 Отчет за период",
        "🔙 Главное меню"
    ]
    keyboard.add(*buttons)
    return keyboard

def create_back_menu():
    """Создает меню с кнопкой Назад"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("🔙 Назад")
    return keyboard

def create_cancel_menu():
    """Создает меню с кнопкой Отмена"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("❌ Отмена")
    return keyboard

def create_employees_keyboard():
    """Создает клавиатуру со списком сотрудников"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, full_name FROM employees WHERE is_active = 1 ORDER BY full_name')
    employees = cursor.fetchall()
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # Добавляем кнопки сотрудников
    for emp_id, full_name in employees:
        keyboard.add(f"👤 {full_name}")
    
    # Добавляем кнопку Отмена
    keyboard.add("❌ Отмена")
    
    conn.close()
    return keyboard

def create_date_keyboard():
    """Создает клавиатуру с датами"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    # Сегодня и вчера
    today = date.today()
    yesterday = today - timedelta(days=1)
    
    buttons = [
        f"📅 {today.strftime('%d.%m.%Y')}",
        f"📅 {yesterday.strftime('%d.%m.%Y')}",
        "📅 Другая дата"
    ]
    keyboard.add(*buttons)
    keyboard.add("❌ Отмена")
    
    return keyboard

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ У вас нет доступа к этому боту")
        return
    
    show_main_menu(message.chat.id)

def show_main_menu(chat_id):
    menu_text = "🏠 ГЛАВНОЕ МЕНЮ УЧЕТА РАБОЧЕГО ВРЕМЕНИ\n\nВыберите действие:"
    bot.send_message(chat_id, menu_text, reply_markup=create_main_menu())

def show_employees_menu(chat_id):
    menu_text = "👥 УПРАВЛЕНИЕ СОТРУДНИКАМИ\n\nВыберите действие:"
    bot.send_message(chat_id, menu_text, reply_markup=create_employees_menu())

def show_reports_menu(chat_id):
    menu_text = "📊 ОТЧЕТЫ И СТАТИСТИКА\n\nВыберите тип отчета:"
    bot.send_message(chat_id, menu_text, reply_markup=create_reports_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    
    if not is_admin(user_id):
        bot.send_message(chat_id, "❌ У вас нет доступа к этому боту")
        return
    
    # Если пользователь в процессе ввода данных
    if user_id in user_states:
        handle_user_state(message)
        return
    
    # Обработка основного меню
    if text == "👥 Сотрудники":
        show_employees_menu(chat_id)
    
    elif text == "✅ Отметить присутствие":
        mark_attendance_today(message)
    
    elif text == "📅 Отметить за прошлую дату":
        mark_attendance_past_date(message)
    
    elif text == "📊 Отчеты":
        show_reports_menu(chat_id)
    
    elif text == "ℹ️ Помощь":
        show_help(message)
    
    # Обработка меню сотрудников
    elif text == "➕ Добавить сотрудника":
        add_employee_start(message)
    
    elif text == "👥 Список сотрудников":
        view_employees(message)
    
    elif text == "✏️ Редактировать сотрудника":
        edit_employee_start(message)
    
    elif text == "🔙 Главное меню":
        show_main_menu(chat_id)
    
    # Обработка меню отчетов
    elif text == "📈 Общий отчет":
        general_report(message)
    
    elif text == "👤 Отчет по сотруднику":
        employee_report_start(message)
    
    elif text == "📅 Отчет за период":
        period_report_start(message)
    
    elif text == "🔙 Назад":
        show_main_menu(chat_id)
    
    elif text == "❌ Отмена":
        if user_id in user_states:
            del user_states[user_id]
        show_main_menu(chat_id)
    
    else:
        show_main_menu(chat_id)

def handle_user_state(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_states[user_id]
    
    if text == "❌ Отмена":
        del user_states[user_id]
        show_main_menu(chat_id)
        return
    
    if state == 'waiting_employee_name':
        employee_name = text
        user_states[user_id] = 'waiting_employee_position'
        user_states[f'{user_id}_name'] = employee_name
        bot.send_message(chat_id, 
            f"Отлично! Сотрудник: {employee_name}\n\n"
            f"Теперь введите должность (или отправьте '-' если не нужно):",
            reply_markup=create_cancel_menu()
        )
    
    elif state == 'waiting_employee_position':
        position = text if text != '-' else None
        employee_name = user_states.get(f'{user_id}_name')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO employees (full_name, position) VALUES (?, ?)', (employee_name, position))
        conn.commit()
        conn.close()
        
        position_text = f"💼 {position}" if position else "💼 Должность не указана"
        bot.send_message(chat_id, 
            f"✅ СОТРУДНИК ДОБАВЛЕН!\n\n"
            f"👤 Имя: {employee_name}\n"
            f"{position_text}")
        
        # Очищаем временные данные
        del user_states[user_id]
        if f'{user_id}_name' in user_states:
            del user_states[f'{user_id}_name']
        
        show_employees_menu(chat_id)
    
    elif state == 'waiting_mark_employee':
        if text.startswith("👤 "):
            employee_name = text[2:]
            user_states[f'{user_id}_employee'] = employee_name
            user_states[user_id] = 'waiting_mark_date'
            
            # Предлагаем выбрать дату
            bot.send_message(chat_id,
                f"Выбран сотрудник: {employee_name}\n\n"
                f"Выберите дату для отметки:",
                reply_markup=create_date_keyboard()
            )
        else:
            bot.send_message(chat_id, "❌ Пожалуйста, выберите сотрудника из списка")
    
    elif state == 'waiting_mark_date':
        if text.startswith("📅 "):
            if text == "📅 Другая дата":
                user_states[user_id] = 'waiting_custom_date'
                bot.send_message(chat_id,
                    "Введите дату в формате ДД.ММ.ГГГГ\nНапример: 25.12.2024",
                    reply_markup=create_cancel_menu()
                )
            else:
                # Извлекаем дату из текста "📅 25.12.2024"
                date_str = text[2:]
                process_date_marking(message, date_str)
        
    elif state == 'waiting_custom_date':
        try:
            # Парсим дату из формата ДД.ММ.ГГГГ
            day, month, year = map(int, text.split('.'))
            mark_date = date(year, month, day)
            date_str = mark_date.strftime('%d.%m.%Y')
            process_date_marking(message, date_str)
        except (ValueError, AttributeError):
            bot.send_message(chat_id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")
    
    elif state == 'waiting_report_employee':
        if text.startswith("👤 "):
            employee_name = text[2:]
            show_employee_report(message, employee_name)
        else:
            bot.send_message(chat_id, "❌ Пожалуйста, выберите сотрудника из списка")
    
    elif state == 'waiting_period_start':
        try:
            day, month, year = map(int, text.split('.'))
            start_date = date(year, month, day)
            user_states[f'{user_id}_start_date'] = start_date
            user_states[user_id] = 'waiting_period_end'
            bot.send_message(chat_id,
                f"Начальная дата: {start_date.strftime('%d.%m.%Y')}\n\n"
                f"Теперь введите конечную дату (ДД.ММ.ГГГГ):",
                reply_markup=create_cancel_menu()
            )
        except (ValueError, AttributeError):
            bot.send_message(chat_id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")
    
    elif state == 'waiting_period_end':
        try:
            day, month, year = map(int, text.split('.'))
            end_date = date(year, month, day)
            start_date = user_states.get(f'{user_id}_start_date')
            
            if end_date < start_date:
                bot.send_message(chat_id, "❌ Конечная дата не может быть раньше начальной")
                return
            
            show_period_report(message, start_date, end_date)
            
        except (ValueError, AttributeError):
            bot.send_message(chat_id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

def process_date_marking(message, date_str):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        day, month, year = map(int, date_str.split('.'))
        mark_date = date(year, month, day)
        employee_name = user_states.get(f'{user_id}_employee')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Находим ID сотрудника
        cursor.execute('SELECT id FROM employees WHERE full_name = ? AND is_active = 1', (employee_name,))
        employee = cursor.fetchone()
        
        if not employee:
            bot.send_message(chat_id, f"❌ Сотрудник '{employee_name}' не найден")
            conn.close()
            return
        
        employee_id = employee[0]
        
        # Проверяем, не отмечен ли уже в эту дату
        cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND check_date = ?', 
                      (employee_id, mark_date.isoformat()))
        
        if cursor.fetchone():
            bot.send_message(chat_id, 
                f"❌ {employee_name} уже отмечен {date_str}!")
        else:
            cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', 
                          (employee_id, mark_date.isoformat()))
            conn.commit()
            bot.send_message(chat_id, 
                f"✅ ПРИСУТСТВИЕ ОТМЕЧЕНО!\n\n"
                f"👤 Сотрудник: {employee_name}\n"
                f"📅 Дата: {date_str}\n"
                f"🕒 Отметил: администратор")
        
        conn.close()
        
        # Очищаем состояние
        del user_states[user_id]
        if f'{user_id}_employee' in user_states:
            del user_states[f'{user_id}_employee']
        
        show_main_menu(chat_id)
        
    except (ValueError, AttributeError):
        bot.send_message(chat_id, "❌ Ошибка обработки даты")

def add_employee_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_employee_name'
    bot.send_message(chat_id,
        "👤 ДОБАВЛЕНИЕ СОТРУДНИКА\n\n"
        "Введите ФИО сотрудника:",
        reply_markup=create_cancel_menu()
    )

def mark_attendance_today(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_mark_employee'
    bot.send_message(chat_id,
        "✅ ОТМЕТКА ПРИСУТСТВИЯ (СЕГОДНЯ)\n\n"
        "Выберите сотрудника:",
        reply_markup=create_employees_keyboard()
    )

def mark_attendance_past_date(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_mark_employee'
    bot.send_message(chat_id,
        "✅ ОТМЕТКА ПРИСУТСТВИЯ (ЗА ПРОШЛУЮ ДАТУ)\n\n"
        "Выберите сотрудника:",
        reply_markup=create_employees_keyboard()
    )

def edit_employee_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Пока просто показываем список сотрудников
    view_employees(message)

def view_employees(message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, full_name, position, is_active FROM employees ORDER BY is_active DESC, full_name')
    employees = cursor.fetchall()
    
    if not employees:
        text = "❌ Сотрудники не найдены"
    else:
        active_count = sum(1 for emp in employees if emp[3])
        text = f"👥 СПИСОК СОТРУДНИКОВ (всего: {len(employees)}, активных: {active_count})\n\n"
        
        for emp in employees:
            emp_id, full_name, position, is_active = emp
            status = "✅" if is_active else "❌"
            position_text = f"💼 {position}" if position else "💼 Должность не указана"
            text += f"{status} {full_name}\n{position_text}\n🆔 ID: {emp_id}\n\n"
    
    bot.send_message(message.chat.id, text)
    conn.close()

def general_report(message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Общая статистика
    cursor.execute('SELECT COUNT(*) FROM employees WHERE is_active = 1')
    active_employees = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT check_date) FROM attendance')
    total_days = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM attendance')
    total_marks = cursor.fetchone()[0]
    
    # Статистика по сотрудникам
    cursor.execute('''
        SELECT e.full_name, COUNT(a.id) as shift_count
        FROM employees e 
        LEFT JOIN attendance a ON e.id = a.employee_id 
        WHERE e.is_active = 1
        GROUP BY e.id 
        ORDER BY shift_count DESC
    ''')
    employee_stats = cursor.fetchall()
    
    report_text = f"📊 ОБЩИЙ ОТЧЕТ\n\n"
    report_text += f"👥 Активных сотрудников: {active_employees}\n"
    report_text += f"📅 Учетных дней: {total_days}\n"
    report_text += f"✅ Всего отметок: {total_marks}\n\n"
    
    report_text += "📈 СТАТИСТИКА ПО СОТРУДНИКАМ:\n\n"
    
    for full_name, shift_count in employee_stats:
        report_text += f"👤 {full_name}: {shift_count} смен\n"
    
    bot.send_message(message.chat.id, report_text)
    conn.close()

def employee_report_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_report_employee'
    bot.send_message(chat_id,
        "👤 ОТЧЕТ ПО СОТРУДНИКУ\n\n"
        "Выберите сотрудника:",
        reply_markup=create_employees_keyboard()
    )

def show_employee_report(message, employee_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Находим сотрудника
    cursor.execute('SELECT id, position FROM employees WHERE full_name = ?', (employee_name,))
    employee = cursor.fetchone()
    
    if not employee:
        bot.send_message(message.chat.id, f"❌ Сотрудник '{employee_name}' не найден")
        conn.close()
        return
    
    employee_id, position = employee
    
    # Получаем все отметки
    cursor.execute('''
        SELECT check_date 
        FROM attendance 
        WHERE employee_id = ? 
        ORDER BY check_date DESC
    ''', (employee_id,))
    
    attendance_records = cursor.fetchall()
    
    position_text = f"💼 {position}" if position else "💼 Должность не указана"
    
    report_text = f"📊 ОТЧЕТ ПО СОТРУДНИКУ\n\n"
    report_text += f"👤 {employee_name}\n"
    report_text += f"{position_text}\n"
    report_text += f"✅ Всего смен: {len(attendance_records)}\n\n"
    
    report_text += "📅 ДАТЫ ПРИСУТСТВИЯ:\n\n"
    
    for record in attendance_records[:20]:  # Показываем последние 20 записей
        check_date = datetime.strptime(record[0], '%Y-%m-%d').strftime('%d.%m.%Y')
        report_text += f"✅ {check_date}\n"
    
    if len(attendance_records) > 20:
        report_text += f"\n... и еще {len(attendance_records) - 20} записей"
    
    bot.send_message(message.chat.id, report_text)
    conn.close()

def period_report_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_period_start'
    bot.send_message(chat_id,
        "📅 ОТЧЕТ ЗА ПЕРИОД\n\n"
        "Введите начальную дату (ДД.ММ.ГГГГ):",
        reply_markup=create_cancel_menu()
    )

def show_period_report(message, start_date, end_date):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Статистика за период
    cursor.execute('''
        SELECT e.full_name, COUNT(a.id) as shift_count
        FROM employees e 
        LEFT JOIN attendance a ON e.id = a.employee_id 
        WHERE a.check_date BETWEEN ? AND ?
        AND e.is_active = 1
        GROUP BY e.id 
        ORDER BY shift_count DESC
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    employee_stats = cursor.fetchall()
    
    total_shifts = sum(count for _, count in employee_stats)
    
    report_text = f"📊 ОТЧЕТ ЗА ПЕРИОД\n\n"
    report_text += f"📅 С {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}\n"
    report_text += f"✅ Всего смен: {total_shifts}\n"
    report_text += f"👥 Сотрудников: {len(employee_stats)}\n\n"
    
    report_text += "📈 СТАТИСТИКА:\n\n"
    
    for full_name, shift_count in employee_stats:
        report_text += f"👤 {full_name}: {shift_count} смен\n"
    
    if not employee_stats:
        report_text += "За указанный период нет данных\n"
    
    bot.send_message(message.chat.id, report_text)
    conn.close()
    
    # Очищаем состояние
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    if f'{user_id}_start_date' in user_states:
        del user_states[f'{user_id}_start_date']

def show_help(message):
    help_text = """ℹ️ ПОМОЩЬ - СИСТЕМА УЧЕТА РАБОЧЕГО ВРЕМЕНИ

👥 СОТРУДНИКИ:
• Добавление новых сотрудников (без привязки к Telegram)
• Просмотр списка всех сотрудников

✅ ОТМЕТКА ПРИСУТСТВИЯ:
• Отметка за сегодняшний день
• Отметка за любую прошлую дату
• Выбор даты из списка или ввод вручную
• Проверка на дублирование отметок

📊 ОТЧЕТЫ:
• Общая статистика по всем сотрудникам
• Подробный отчет по каждому сотруднику
• Отчеты за произвольный период
• Подсчет количества смен

📅 ФОРМАТ ДАТ:
• Используйте формат ДД.ММ.ГГГГ (25.12.2024)
• Можно выбирать из готовых вариантов
• Можно вводить вручную

💡 СИСТЕМА АВТОМАТИЧЕСКИ:
• Считает количество смен
• Проверяет дублирование отметок
• Формирует статистику"""
    
    bot.send_message(message.chat.id, help_text)

if __name__ == '__main__':
    init_db()
    logger.info("🤖 Бот запущен с расширенным функционалом отметок!")
    bot.infinity_polling()
