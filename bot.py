import os
import logging
import sys
import time
from datetime import date, datetime, timedelta

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def fix_database_url(url):
    """Исправляет DATABASE_URL если нужно"""
    if url and url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url

def check_environment():
    """Проверяем переменные окружения"""
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    DATABASE_URL = os.environ.get('DATABASE_URL')
    ADMIN_ID = os.environ.get('ADMIN_ID')
    
    if not all([BOT_TOKEN, DATABASE_URL, ADMIN_ID]):
        logger.error("❌ Отсутствуют необходимые переменные окружения")
        logger.error(f"BOT_TOKEN: {'✅' if BOT_TOKEN else '❌'}")
        logger.error(f"DATABASE_URL: {'✅' if DATABASE_URL else '❌'}")
        logger.error(f"ADMIN_ID: {'✅' if ADMIN_ID else '❌'}")
        return None, None, None
    
    DATABASE_URL = fix_database_url(DATABASE_URL)
    logger.info(f"✅ Переменные окружения загружены. DATABASE_URL: {DATABASE_URL[:30]}...")
    return BOT_TOKEN, DATABASE_URL, ADMIN_ID

# Проверяем переменные
BOT_TOKEN, DATABASE_URL, ADMIN_ID = check_environment()
if not all([BOT_TOKEN, DATABASE_URL, ADMIN_ID]):
    sys.exit(1)

# Импортируем модули
try:
    import pg8000
    import telebot
    from telebot import types
    from flask import Flask
    import threading
    from urllib.parse import urlparse
except ImportError as e:
    logger.error(f"❌ Ошибка импорта: {e}")
    sys.exit(1)

# Инициализируем бота с обработкой ошибок
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    logger.info("✅ Бот инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации бота: {e}")
    sys.exit(1)

# Flask app для поддержания активности
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/ping')
def ping():
    return "pong", 200

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

user_states = {}

def parse_db_url(db_url):
    """Парсит DATABASE_URL для pg8000"""
    try:
        parsed = urlparse(db_url)
        return {
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'user': parsed.username,
            'password': parsed.password,
            'database': parsed.path[1:] if parsed.path else None
        }
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга DATABASE_URL: {e}")
        return None

def get_connection():
    """Создает соединение с PostgreSQL через pg8000"""
    try:
        db_config = parse_db_url(DATABASE_URL)
        if not db_config:
            logger.error("❌ Не удалось распарсить DATABASE_URL")
            return None
        
        logger.info(f"🔌 Подключение к БД: {db_config['host']}:{db_config['port']}, база: {db_config['database']}")
        
        conn = pg8000.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database=db_config['database'],
            ssl_context=True
        )
        logger.info("✅ Подключение к БД установлено")
        return conn
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        return None

def test_db_connection():
    """Тестируем подключение к базе данных"""
    logger.info("🔍 ТЕСТИРОВАНИЕ ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ...")
    
    # Проверяем переменные
    logger.info(f"📊 DATABASE_URL: {DATABASE_URL[:50]}...")
    
    # Парсим URL
    db_config = parse_db_url(DATABASE_URL)
    if db_config:
        logger.info(f"✅ Конфигурация БД: host={db_config['host']}, db={db_config['database']}")
    else:
        logger.error("❌ Ошибка парсинга DATABASE_URL")
        return False
    
    # Тестируем подключение
    conn = get_connection()
    if not conn:
        logger.error("❌ Не удалось подключиться к БД")
        return False
    
    try:
        # Тестируем простой запрос
        with conn.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()
            logger.info(f"✅ Подключение к БД успешно: {version[0][:50]}...")
        
        # Проверяем существование таблиц
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = cursor.fetchall()
        logger.info(f"📋 Таблицы в БД: {[table[0] for table in tables]}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования БД: {e}")
        return False
    finally:
        conn.close()

def test_tables(conn):
    """Проверяем создание таблиц"""
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM employees")
            count = cursor.fetchone()[0]
            logger.info(f"📊 В таблице employees записей: {count}")
            
            cursor.execute("SELECT COUNT(*) FROM admins")
            count = cursor.fetchone()[0]
            logger.info(f"📊 В таблице admins записей: {count}")
            
            cursor.execute("SELECT COUNT(*) FROM attendance")
            count = cursor.fetchone()[0]
            logger.info(f"📊 В таблице attendance записей: {count}")
    except Exception as e:
        logger.error(f"❌ Ошибка проверки таблиц: {e}")

def init_db():
    """Инициализация базы данных"""
    logger.info("🔄 ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ...")
    
    # Сначала тестируем подключение
    if not test_db_connection():
        logger.error("❌ Тестирование подключения к БД не удалось")
        return False
    
    conn = get_connection()
    if not conn:
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
            logger.info("✅ Таблица employees создана/проверена")
            
            # Таблица посещаемости
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendance (
                    id SERIAL PRIMARY KEY,
                    employee_id INTEGER REFERENCES employees(id),
                    check_date DATE NOT NULL,
                    marked_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(employee_id, check_date)
                )
            ''')
            logger.info("✅ Таблица attendance создана/проверена")
            
            # Таблица администраторов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER UNIQUE
                )
            ''')
            logger.info("✅ Таблица admins создана/проверена")
            
            # Добавляем администратора
            cursor.execute(
                'INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING', 
                (int(ADMIN_ID),)
            )
            logger.info(f"✅ Администратор добавлен: {ADMIN_ID}")
            
        conn.commit()
        logger.info("✅ База данных инициализирована")
        
        # Проверяем, что таблицы созданы
        test_tables(conn)
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def execute_query(query, params=None, fetch=False):
    """Универсальная функция выполнения запросов"""
    logger.info(f"🔍 ВЫПОЛНЕНИЕ ЗАПРОСА: {query[:100]}...")
    if params:
        logger.info(f"🔍 ПАРАМЕТРЫ: {params}")
    
    conn = get_connection()
    if not conn:
        logger.error("❌ Нет соединения с БД")
        return None
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            
            if fetch:
                result = cursor.fetchall()
                logger.info(f"✅ Запрос выполнен (fetch): {query[:50]}... Найдено записей: {len(result)}")
            else:
                conn.commit()
                result = True
                logger.info(f"✅ Запрос выполнен: {query[:50]}...")
                
            return result
    except Exception as e:
        logger.error(f"❌ Ошибка выполнения запроса: {e}")
        logger.error(f"❌ Запрос: {query}")
        logger.error(f"❌ Параметры: {params}")
        conn.rollback()
        return None
    finally:
        conn.close()

def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
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
        "✅ Отметить сегодня", 
        "📊 Отчеты",
        "📅 Отметить за дату",
        "ℹ️ Помощь"
    ]
    keyboard.add(*buttons)
    return keyboard

def create_employees_menu():
    """Создает меню сотрудников"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "➕ Добавить сотрудника",
        "📋 Список сотрудников",
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
    employees = execute_query(
        'SELECT id, full_name FROM employees WHERE is_active = TRUE ORDER BY full_name', 
        fetch=True
    )
    
    if not employees:
        logger.info("❌ Нет сотрудников для создания клавиатуры")
        return None
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    for emp in employees:
        keyboard.add(f"👤 {emp[1]}")  # emp[1] - full_name
    
    keyboard.add("❌ Отмена")
    logger.info(f"✅ Создана клавиатура с {len(employees)} сотрудниками")
    return keyboard

def create_date_keyboard():
    """Создает клавиатуру с датами"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    today = date.today()
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    
    buttons = [
        f"📅 {today.strftime('%d.%m.%Y')}",
        f"📅 {yesterday.strftime('%d.%m.%Y')}",
        f"📅 {day_before.strftime('%d.%m.%Y')}",
        "📅 Другая дата"
    ]
    keyboard.add(*buttons)
    keyboard.add("❌ Отмена")
    
    return keyboard

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    logger.info(f"👤 Пользователь {user_id} запустил бота")
    
    if not is_admin(user_id):
        bot.send_message(chat_id, "❌ У вас нет доступа к этому боту")
        logger.warning(f"❌ Отказано в доступе пользователю {user_id}")
        return
    
    show_main_menu(chat_id)

@bot.message_handler(commands=['debug'])
def debug_db(message):
    """Команда для отладки базы данных"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ У вас нет доступа к этой команде")
        return
    
    logger.info("🔧 ЗАПУСК КОМАНДЫ DEBUG")
    
    # Тестируем подключение
    test_result = test_db_connection()
    
    # Проверяем сотрудников
    employees = execute_query('SELECT * FROM employees', fetch=True)
    
    # Проверяем таблицы
    tables = execute_query("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """, fetch=True)
    
    # Формируем отчет
    report = "🔧 ОТЧЕТ ОТЛАДКИ БАЗЫ ДАННЫХ\n\n"
    
    if test_result:
        report += "✅ Подключение к БД: УСПЕШНО\n"
    else:
        report += "❌ Подключение к БД: ОШИБКА\n"
    
    if employees:
        report += f"✅ Сотрудников в БД: {len(employees)}\n"
        for emp in employees:
            report += f"   👤 {emp[1]} (ID: {emp[0]})\n"
    else:
        report += "❌ Сотрудников в БД: 0\n"
    
    if tables:
        table_names = [table[0] for table in tables]
        report += f"✅ Таблицы в БД: {', '.join(table_names)}\n"
    else:
        report += "❌ Таблицы в БД: не найдены\n"
    
    bot.send_message(message.chat.id, report)
    logger.info("✅ Отчет отладки отправлен")

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
    
    logger.info(f"📨 Сообщение от {user_id}: {text}")
    
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
    
    elif text == "✅ Отметить сегодня":
        mark_attendance_today(message)
    
    elif text == "📅 Отметить за дату":
        mark_attendance_date(message)
    
    elif text == "📊 Отчеты":
        show_reports_menu(chat_id)
    
    elif text == "ℹ️ Помощь":
        show_help(message)
    
    # Обработка меню сотрудников
    elif text == "➕ Добавить сотрудника":
        add_employee_start(message)
    
    elif text == "📋 Список сотрудников":
        view_employees(message)
    
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
    
    logger.info(f"🔄 Обработка состояния {state} для пользователя {user_id}")
    
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
        
        logger.info(f"📝 Добавление сотрудника: {employee_name}, должность: {position}")
        
        result = execute_query(
            'INSERT INTO employees (full_name, position) VALUES (%s, %s)',
            (employee_name, position)
        )
        
        if result:
            position_text = f"💼 {position}" if position else "💼 Должность не указана"
            bot.send_message(chat_id, 
                f"✅ СОТРУДНИК ДОБАВЛЕН!\n\n"
                f"👤 Имя: {employee_name}\n"
                f"{position_text}")
            logger.info(f"✅ Успешно добавлен сотрудник: {employee_name}")
        else:
            bot.send_message(chat_id, "❌ Ошибка при добавлении сотрудника")
            logger.error(f"❌ Ошибка добавления сотрудника: {employee_name}")
        
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
            
            logger.info(f"✅ Выбран сотрудник для отметки: {employee_name}")
            
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
        
        logger.info(f"📅 Обработка отметки: {employee_name} за {date_str}")
        
        # Находим ID сотрудника
        result = execute_query(
            'SELECT id FROM employees WHERE full_name = %s AND is_active = TRUE', 
            (employee_name,), 
            fetch=True
        )
        
        if not result:
            bot.send_message(chat_id, f"❌ Сотрудник '{employee_name}' не найден")
            logger.error(f"❌ Сотрудник не найден: {employee_name}")
            return
        
        employee_id = result[0][0]
        
        # Проверяем, не отмечен ли уже в эту дату
        existing = execute_query(
            'SELECT id FROM attendance WHERE employee_id = %s AND check_date = %s', 
            (employee_id, mark_date), 
            fetch=True
        )
        
        if existing:
            bot.send_message(chat_id, 
                f"❌ {employee_name} уже отмечен {date_str}!")
            logger.info(f"⚠️ Дублирование отметки: {employee_name} за {date_str}")
        else:
            # Добавляем отметку
            success = execute_query(
                'INSERT INTO attendance (employee_id, check_date) VALUES (%s, %s)', 
                (employee_id, mark_date)
            )
            if success:
                bot.send_message(chat_id, 
                    f"✅ ПРИСУТСТВИЕ ОТМЕЧЕНО!\n\n"
                    f"👤 Сотрудник: {employee_name}\n"
                    f"📅 Дата: {date_str}")
                logger.info(f"✅ Успешная отметка: {employee_name} за {date_str}")
            else:
                bot.send_message(chat_id, "❌ Ошибка при сохранении отметки")
                logger.error(f"❌ Ошибка сохранения отметки: {employee_name} за {date_str}")
        
        # Очищаем состояние
        del user_states[user_id]
        if f'{user_id}_employee' in user_states:
            del user_states[f'{user_id}_employee']
        
        show_main_menu(chat_id)
        
    except (ValueError, AttributeError) as e:
        bot.send_message(chat_id, "❌ Ошибка обработки даты")
        logger.error(f"❌ Ошибка обработки даты: {e}")

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
    
    employees_keyboard = create_employees_keyboard()
    if not employees_keyboard:
        bot.send_message(chat_id, "❌ Нет сотрудников для отметки")
        logger.info("❌ Нет сотрудников для отметки сегодня")
        return
    
    today = date.today().strftime('%d.%m.%Y')
    bot.send_message(chat_id,
        f"✅ ОТМЕТКА ПРИСУТСТВИЯ (СЕГОДНЯ)\n\nДата: {today}\nВыберите сотрудника:",
        reply_markup=employees_keyboard
    )

def mark_attendance_date(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_mark_employee'
    
    employees_keyboard = create_employees_keyboard()
    if not employees_keyboard:
        bot.send_message(chat_id, "❌ Нет сотрудников для отметки")
        return
    
    bot.send_message(chat_id,
        "✅ ОТМЕТКА ПРИСУТСТВИЯ (ЗА ДАТУ)\n\nВыберите сотрудника:",
        reply_markup=employees_keyboard
    )

def view_employees(message):
    employees = execute_query(
        'SELECT id, full_name, position, is_active FROM employees ORDER BY is_active DESC, full_name', 
        fetch=True
    )
    
    if not employees:
        bot.send_message(message.chat.id, "❌ Сотрудники не найдены")
        logger.info("❌ В базе нет сотрудников")
        return
    
    text = "👥 СПИСОК СОТРУДНИКОВ\n\n"
    for emp in employees:
        emp_id, full_name, position, is_active = emp
        status = "✅" if is_active else "❌"
        position_text = f"💼 {position}" if position else "💼 Должность не указана"
        text += f"{status} {full_name}\n{position_text}\n🆔 ID: {emp_id}\n\n"
    
    bot.send_message(message.chat.id, text)
    logger.info(f"✅ Показан список из {len(employees)} сотрудников")

def general_report(message):
    # Общая статистика
    employees_count = execute_query('SELECT COUNT(*) FROM employees WHERE is_active = TRUE', fetch=True)
    attendance_count = execute_query('SELECT COUNT(*) FROM attendance', fetch=True)
    total_days = execute_query('SELECT COUNT(DISTINCT check_date) FROM attendance', fetch=True)
    
    if not all([employees_count, attendance_count, total_days]):
        bot.send_message(message.chat.id, "❌ Ошибка получения данных")
        logger.error("❌ Ошибка получения данных для общего отчета")
        return
    
    # Статистика по сотрудникам
    employee_stats = execute_query('''
        SELECT e.full_name, COUNT(a.id) as shift_count
        FROM employees e 
        LEFT JOIN attendance a ON e.id = a.employee_id 
        WHERE e.is_active = TRUE
        GROUP BY e.id, e.full_name 
        ORDER BY shift_count DESC
    ''', fetch=True)
    
    report_text = f"📊 ОБЩИЙ ОТЧЕТ\n\n"
    report_text += f"👥 Активных сотрудников: {employees_count[0][0]}\n"
    report_text += f"📅 Учетных дней: {total_days[0][0]}\n"
    report_text += f"✅ Всего отметок: {attendance_count[0][0]}\n\n"
    
    report_text += "📈 СТАТИСТИКА ПО СОТРУДНИКАМ:\n\n"
    
    if employee_stats:
        for full_name, shift_count in employee_stats:
            report_text += f"👤 {full_name}: {shift_count} смен\n"
    else:
        report_text += "Нет данных о сменах\n"
    
    bot.send_message(message.chat.id, report_text)
    logger.info("✅ Показан общий отчет")

def employee_report_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    employees_keyboard = create_employees_keyboard()
    if not employees_keyboard:
        bot.send_message(chat_id, "❌ Нет сотрудников для отчета")
        return
    
    user_states[user_id] = 'waiting_report_employee'
    bot.send_message(chat_id,
        "👤 ОТЧЕТ ПО СОТРУДНИКУ\n\n"
        "Выберите сотрудника:",
        reply_markup=employees_keyboard
    )

def show_employee_report(message, employee_name):
    # Находим сотрудника
    employee = execute_query(
        'SELECT id, position FROM employees WHERE full_name = %s', 
        (employee_name,), 
        fetch=True
    )
    
    if not employee:
        bot.send_message(message.chat.id, f"❌ Сотрудник '{employee_name}' не найден")
        return
    
    # Правильное обращение к элементам кортежа
    employee_id = employee[0][0]  # id
    position = employee[0][1]     # position
    
    # Получаем все отметки
    attendance_records = execute_query(
        'SELECT check_date FROM attendance WHERE employee_id = %s ORDER BY check_date DESC', 
        (employee_id,), 
        fetch=True
    )
    
    position_text = f"💼 {position}" if position else "💼 Должность не указана"
    
    report_text = f"📊 ОТЧЕТ ПО СОТРУДНИКУ\n\n"
    report_text += f"👤 {employee_name}\n"
    report_text += f"{position_text}\n"
    report_text += f"✅ Всего смен: {len(attendance_records) if attendance_records else 0}\n\n"
    
    report_text += "📅 ДАТЫ ПРИСУТСТВИЯ:\n\n"
    
    if attendance_records:
        for record in attendance_records[:15]:  # Показываем только последние 15 записей
            check_date = record[0].strftime('%d.%m.%Y')
            report_text += f"✅ {check_date}\n"
        
        if len(attendance_records) > 15:
            report_text += f"\n... и еще {len(attendance_records) - 15} записей"
    else:
        report_text += "Нет данных о присутствии\n"
    
    bot.send_message(message.chat.id, report_text)
    logger.info(f"✅ Показан отчет по сотруднику: {employee_name}")

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
    # Статистика за период
    employee_stats = execute_query('''
        SELECT e.full_name, COUNT(a.id) as shift_count
        FROM employees e 
        LEFT JOIN attendance a ON e.id = a.employee_id 
        WHERE a.check_date BETWEEN %s AND %s
        AND e.is_active = TRUE
        GROUP BY e.id, e.full_name 
        ORDER BY shift_count DESC
    ''', (start_date, end_date), fetch=True)
    
    total_shifts = sum(count for _, count in employee_stats) if employee_stats else 0
    
    report_text = f"📊 ОТЧЕТ ЗА ПЕРИОД\n\n"
    report_text += f"📅 С {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}\n"
    report_text += f"✅ Всего смен: {total_shifts}\n"
    report_text += f"👥 Сотрудников: {len(employee_stats) if employee_stats else 0}\n\n"
    
    report_text += "📈 СТАТИСТИКА:\n\n"
    
    if employee_stats:
        for full_name, shift_count in employee_stats:
            report_text += f"👤 {full_name}: {shift_count} смен\n"
