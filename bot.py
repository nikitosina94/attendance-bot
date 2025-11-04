import os
import logging
import psycopg
import time
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
DATABASE_URL = os.environ.get('DATABASE_URL')

# Проверяем обязательные переменные
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не установлен!")
    exit(1)

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL не установлен!")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
user_states = {}

def get_connection_with_retry(max_retries=3, delay=2):
    """Создает соединение с PostgreSQL с повторными попытками"""
    for attempt in range(max_retries):
        try:
            conn = psycopg.connect(DATABASE_URL)
            logger.info(f"✅ Успешное подключение к PostgreSQL (попытка {attempt + 1})")
            return conn
        except Exception as e:
            logger.warning(f"⚠️ Попытка {attempt + 1} не удалась: {e}")
            if attempt < max_retries - 1:
                logger.info(f"🔄 Повторная попытка через {delay} секунд...")
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"❌ Все попытки подключения не удались: {e}")
                return None

def init_db():
    """Инициализация таблиц"""
    conn = get_connection_with_retry()
    if not conn:
        logger.error("❌ Не удалось подключиться к базе данных")
        return False
    
    try:
        with conn.cursor() as cursor:
            # Таблица сотрудников
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS employees (
                    id SERIAL PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    position TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица посещаемости
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendance (
                    id SERIAL PRIMARY KEY,
                    employee_id INTEGER REFERENCES employees(id),
                    check_date DATE,
                    marked_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица администраторов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER UNIQUE
                )
            ''')
            
            # Добавляем администратора
            admin_id = os.environ.get('ADMIN_ID')
            if admin_id:
                cursor.execute(
                    'INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING', 
                    (int(admin_id),)
                )
            
            conn.commit()
            logger.info("✅ База данных инициализирована")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def execute_query(query, params=None, fetch=False):
    """Универсальная функция выполнения запросов"""
    conn = get_connection_with_retry()
    if not conn:
        return None
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            
            if fetch:
                result = cursor.fetchall()
            else:
                conn.commit()
                result = None
                
            return result
    except Exception as e:
        logger.error(f"❌ Ошибка выполнения запроса: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def is_admin(user_id):
    result = execute_query(
        'SELECT * FROM admins WHERE user_id = %s', 
        (user_id,), 
        fetch=True
    )
    return bool(result)

def create_main_menu():
    """Создает основное меню"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "👥 Сотрудники",
        "✅ Отметить присутствие", 
        "📊 Отчеты",
        "📅 Отметить за дату",
        "ℹ️ Помощь"
    ]
    keyboard.add(*buttons)
    return keyboard

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ У вас нет доступа к этому боту")
        return
    
    # Проверяем соединение с базой
    test_result = execute_query('SELECT 1', fetch=True)
    if not test_result:
        bot.send_message(message.chat.id, "⚠️ Проблемы с подключением к базе данных")
        return
    
    bot.send_message(
        message.chat.id,
        "🏠 Бот для учета рабочего времени\n\nБаза данных: ✅ подключена\nВыберите действие:",
        reply_markup=create_main_menu()
    )

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Нет доступа")
        return
    
    if text == "👥 Сотрудники":
        show_employees_menu(message)
    elif text == "✅ Отметить присутствие":
        mark_attendance_today(message)
    elif text == "📅 Отметить за дату":
        mark_attendance_date(message)
    elif text == "📊 Отчеты":
        show_reports(message)
    elif text == "ℹ️ Помощь":
        show_help(message)
    else:
        bot.send_message(message.chat.id, "Используйте кнопки меню")

def show_employees_menu(message):
    # Создаем меню управления сотрудниками
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("➕ Добавить сотрудника", "📋 Список сотрудников")
    keyboard.add("🔙 Главное меню")
    
    # Получаем статистику
    result = execute_query('SELECT COUNT(*) FROM employees', fetch=True)
    count = result[0][0] if result else 0
    
    bot.send_message(
        message.chat.id, 
        f"👥 Управление сотрудниками\n\nВсего сотрудников: {count}",
        reply_markup=keyboard
    )

def mark_attendance_today(message):
    today = date.today()
    
    # Получаем список сотрудников
    employees = execute_query('SELECT id, full_name FROM employees WHERE is_active = TRUE', fetch=True)
    
    if not employees:
        bot.send_message(message.chat.id, "❌ Нет сотрудников для отметки")
        return
    
    # Создаем клавиатуру с сотрудниками
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for emp_id, full_name in employees:
        keyboard.add(f"✅ {full_name}")
    keyboard.add("🔙 Главное меню")
    
    user_states[message.from_user.id] = {'action': 'mark_today', 'date': today}
    
    bot.send_message(
        message.chat.id,
        f"✅ Отметка присутствия\n\nДата: {today.strftime('%d.%m.%Y')}\nВыберите сотрудника:",
        reply_markup=keyboard
    )

def mark_attendance_date(message):
    # Создаем клавиатуру с датами
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    today = date.today()
    
    # Добавляем последние 7 дней
    for i in range(7):
        day = today - timedelta(days=i)
        keyboard.add(f"📅 {day.strftime('%d.%m.%Y')}")
    
    keyboard.add("🔙 Главное меню")
    
    user_states[message.from_user.id] = {'action': 'choose_date'}
    
    bot.send_message(
        message.chat.id,
        "📅 Выберите дату для отметки:",
        reply_markup=keyboard
    )

def show_reports(message):
    # Получаем статистику
    employees_count = execute_query('SELECT COUNT(*) FROM employees', fetch=True)
    attendance_count = execute_query('SELECT COUNT(*) FROM attendance', fetch=True)
    active_employees = execute_query('SELECT COUNT(*) FROM employees WHERE is_active = TRUE', fetch=True)
    
    if not all([employees_count, attendance_count, active_employees]):
        bot.send_message(message.chat.id, "❌ Ошибка получения данных")
        return
    
    report_text = f"📊 ОБЩИЙ ОТЧЕТ\n\n"
    report_text += f"👥 Всего сотрудников: {employees_count[0][0]}\n"
    report_text += f"✅ Активных: {active_employees[0][0]}\n"
    report_text += f"📈 Всего отметок: {attendance_count[0][0]}\n"
    report_text += f"📅 Дата: {date.today().strftime('%d.%m.%Y')}"
    
    # Добавляем топ сотрудников по отметкам
    top_employees = execute_query('''
        SELECT e.full_name, COUNT(a.id) as shift_count 
        FROM employees e 
        LEFT JOIN attendance a ON e.id = a.employee_id 
        WHERE e.is_active = TRUE
        GROUP BY e.id, e.full_name 
        ORDER BY shift_count DESC 
        LIMIT 5
    ''', fetch=True)
    
    if top_employees:
        report_text += "\n\n🏆 ТОП сотрудников:\n"
        for i, (name, count) in enumerate(top_employees, 1):
            report_text += f"{i}. {name}: {count} смен\n"
    
    bot.send_message(message.chat.id, report_text)

def show_help(message):
    help_text = """ℹ️ ПОМОЩЬ - СИСТЕМА УЧЕТА РАБОЧЕГО ВРЕМЕНИ

👥 СОТРУДНИКИ:
• Добавление новых сотрудников
• Просмотр списка всех сотрудников

✅ ОТМЕТКА ПРИСУТСТВИЯ:
• Отметка за сегодняшний день
• Отметка за любую прошлую дату

📊 ОТЧЕТЫ:
• Общая статистика по всем сотрудникам
• Подсчет количества смен

💾 ХРАНЕНИЕ ДАННЫХ:
• Данные сохраняются в PostgreSQL
• Не теряются при перезагрузке"""
    
    bot.send_message(message.chat.id, help_text)

# Обработка выбора сотрудника для отметки
@bot.message_handler(func=lambda message: message.text.startswith("✅ "))
def handle_employee_selection(message):
    user_id = message.from_user.id
    employee_name = message.text[2:]  # Убираем "✅ "
    
    if user_id not in user_states:
        bot.send_message(message.chat.id, "❌ Сессия устарела, начните заново")
        return
    
    state = user_states[user_id]
    
    # Находим ID сотрудника
    result = execute_query('SELECT id FROM employees WHERE full_name = %s', (employee_name,), fetch=True)
    if not result:
        bot.send_message(message.chat.id, f"❌ Сотрудник '{employee_name}' не найден")
        return
    
    employee_id = result[0][0]
    mark_date = state.get('date', date.today())
    
    # Проверяем, не отмечен ли уже
    existing = execute_query(
        'SELECT id FROM attendance WHERE employee_id = %s AND check_date = %s', 
        (employee_id, mark_date), 
        fetch=True
    )
    
    if existing:
        bot.send_message(message.chat.id, f"❌ {employee_name} уже отмечен {mark_date.strftime('%d.%m.%Y')}")
    else:
        # Добавляем отметку
        execute_query(
            'INSERT INTO attendance (employee_id, check_date) VALUES (%s, %s)', 
            (employee_id, mark_date)
        )
        bot.send_message(
            message.chat.id, 
            f"✅ УСПЕХ!\n\n{employee_name} отмечен {mark_date.strftime('%d.%m.%Y')}"
        )
    
    # Очищаем состояние
    del user_states[user_id]
    show_main_menu(message.chat.id)

# Обработка выбора даты
@bot.message_handler(func=lambda message: message.text.startswith("📅 "))
def handle_date_selection(message):
    user_id = message.from_user.id
    date_str = message.text[2:]  # Убираем "📅 "
    
    try:
        day, month, year = map(int, date_str.split('.'))
        selected_date = date(year, month, day)
        
        # Получаем список сотрудников
        employees = execute_query('SELECT id, full_name FROM employees WHERE is_active = TRUE', fetch=True)
        
        if not employees:
            bot.send_message(message.chat.id, "❌ Нет сотрудников для отметки")
            return
        
        # Создаем клавиатуру с сотрудниками
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        for emp_id, full_name in employees:
            keyboard.add(f"✅ {full_name}")
        keyboard.add("🔙 Главное меню")
        
        user_states[user_id] = {'action': 'mark_date', 'date': selected_date}
        
        bot.send_message(
            message.chat.id,
            f"✅ Отметка присутствия\n\nДата: {date_str}\nВыберите сотрудника:",
            reply_markup=keyboard
        )
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка формата даты")

# Обработка кнопки "Добавить сотрудника"
@bot.message_handler(func=lambda message: message.text == "➕ Добавить сотрудника")
def add_employee_start(message):
    user_states[message.from_user.id] = {'action': 'add_employee_name'}
    bot.send_message(
        message.chat.id,
        "👤 ДОБАВЛЕНИЕ СОТРУДНИКА\n\nВведите ФИО сотрудника:",
        reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("❌ Отмена")
    )

# Обработка ввода имени сотрудника
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('action') == 'add_employee_name')
def add_employee_name(message):
    if message.text == "❌ Отмена":
        del user_states[message.from_user.id]
        show_main_menu(message.chat.id)
        return
    
    user_states[message.from_user.id] = {
        'action': 'add_employee_position', 
        'name': message.text
    }
    
    bot.send_message(
        message.chat.id,
        f"👤 ФИО: {message.text}\n\nТеперь введите должность (или '-' если не нужно):",
        reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("❌ Отмена")
    )

# Обработка ввода должности
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('action') == 'add_employee_position')
def add_employee_position(message):
    if message.text == "❌ Отмена":
        del user_states[message.from_user.id]
        show_main_menu(message.chat.id)
        return
    
    user_data = user_states[message.from_user.id]
    employee_name = user_data['name']
    position = message.text if message.text != '-' else None
    
    # Добавляем сотрудника в базу
    result = execute_query(
        'INSERT INTO employees (full_name, position) VALUES (%s, %s) RETURNING id',
        (employee_name, position),
        fetch=True
    )
    
    if result:
        position_text = f"💼 {position}" if position else ""
        bot.send_message(
            message.chat.id,
            f"✅ СОТРУДНИК ДОБАВЛЕН!\n\n👤 {employee_name}\n{position_text}\n🆔 ID: {result[0][0]}"
        )
    else:
        bot.send_message(message.chat.id, "❌ Ошибка при добавлении сотрудника")
    
    del user_states[message.from_user.id]
    show_main_menu(message.chat.id)

# Обработка кнопки "Список сотрудников"
@bot.message_handler(func=lambda message: message.text == "📋 Список сотрудников")
def show_employees_list(message):
    employees = execute_query(
        'SELECT id, full_name, position, is_active FROM employees ORDER BY is_active DESC, full_name', 
        fetch=True
    )
    
    if not employees:
        bot.send_message(message.chat.id, "❌ Сотрудники не найдены")
        return
    
    text = "👥 СПИСОК СОТРУДНИКОВ\n\n"
    for emp_id, full_name, position, is_active in employees:
        status = "✅" if is_active else "❌"
        position_text = f"💼 {position}" if position else ""
        text += f"{status} {full_name}\n{position_text}\n🆔 ID: {emp_id}\n\n"
    
    bot.send_message(message.chat.id, text)

# Обработка кнопки "Главное меню"
@bot.message_handler(func=lambda message: message.text == "🔙 Главное меню")
def back_to_main(message):
    if message.from_user.id in user_states:
        del user_states[message.from_user.id]
    show_main_menu(message.chat.id)

def show_main_menu(chat_id):
    bot.send_message(chat_id, "🏠 Главное меню:", reply_markup=create_main_menu())

if __name__ == '__main__':
    logger.info("🔄 Запуск бота с psycopg 3.2.12...")
    
    # Даем время на инициализацию базы
    time.sleep(3)
    
    if init_db():
        logger.info("✅ Бот успешно запущен!")
        bot.infinity_polling()
    else:
        logger.error("❌ Не удалось инициализировать базу данных")
