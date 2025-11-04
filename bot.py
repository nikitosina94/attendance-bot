import os
import logging
import sys
import time
from datetime import date, datetime, timedelta

# Детальная настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Изменили на DEBUG для максимальной детализации
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
    
    logger.debug(f"🔧 Проверка переменных: BOT_TOKEN={bool(BOT_TOKEN)}, DATABASE_URL={bool(DATABASE_URL)}, ADMIN_ID={bool(ADMIN_ID)}")
    
    if not all([BOT_TOKEN, DATABASE_URL, ADMIN_ID]):
        logger.error("❌ Отсутствуют необходимые переменные окружения")
        return None, None, None
    
    DATABASE_URL = fix_database_url(DATABASE_URL)
    logger.info(f"✅ Переменные окружения загружены")
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
    logger.info("✅ Все модули успешно импортированы")
except ImportError as e:
    logger.error(f"❌ Ошибка импорта: {e}")
    sys.exit(1)

# Инициализируем бота
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
    logger.debug(f"🔧 Парсинг DATABASE_URL: {db_url[:50]}...")
    try:
        parsed = urlparse(db_url)
        config = {
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'user': parsed.username,
            'password': '***' if parsed.password else None,  # Скрываем пароль в логах
            'database': parsed.path[1:] if parsed.path else None
        }
        logger.debug(f"🔧 Результат парсинга: {config}")
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
    logger.debug("🔧 Попытка подключения к БД...")
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

def execute_query(query, params=None, fetch=False):
    """Универсальная функция выполнения запросов"""
    logger.debug(f"🎯 ВЫПОЛНЕНИЕ ЗАПРОСА: {query}")
    if params:
        logger.debug(f"🎯 ПАРАМЕТРЫ: {params}")
    
    conn = get_connection()
    if not conn:
        logger.error("❌ Нет соединения с БД для выполнения запроса")
        return None
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            
            if fetch:
                result = cursor.fetchall()
                logger.debug(f"✅ Запрос выполнен (fetch). Найдено записей: {len(result)}")
                if result:
                    logger.debug(f"📊 Результат: {result}")
            else:
                conn.commit()
                result = True
                logger.debug("✅ Запрос выполнен (insert/update)")
                
            return result
    except Exception as e:
        logger.error(f"❌ Ошибка выполнения запроса: {e}")
        logger.error(f"❌ Запрос: {query}")
        logger.error(f"❌ Параметры: {params}")
        conn.rollback()
        return None
    finally:
        conn.close()

def init_db():
    """Инициализация базы данных"""
    logger.info("🔄 ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ...")
    
    conn = get_connection()
    if not conn:
        logger.error("❌ Не удалось подключиться к БД для инициализации")
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
        return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    logger.debug(f"🔍 Проверка прав администратора для пользователя {user_id}")
    result = execute_query(
        'SELECT * FROM admins WHERE user_id = %s', 
        (user_id,), 
        fetch=True
    )
    is_admin = bool(result)
    logger.debug(f"🔍 Результат проверки прав: {is_admin}")
    return is_admin

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
    logger.debug("🔧 Создание клавиатуры сотрудников...")
    employees = execute_query(
        'SELECT id, full_name FROM employees WHERE is_active = TRUE ORDER BY full_name', 
        fetch=True
    )
    
    logger.debug(f"🔧 Результат запроса сотрудников: {employees}")
    
    if not employees:
        logger.warning("⚠️ Нет сотрудников для создания клавиатуры")
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
    
    # Проверяем сотрудников
    employees = execute_query('SELECT * FROM employees', fetch=True)
    
    # Проверяем таблицы
    tables = execute_query("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """, fetch=True)
    
    # Проверяем конкретно таблицу employees
    employees_table = execute_query("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'employees'
    """, fetch=True)
    
    # Формируем отчет
    report = "🔧 ДЕТАЛЬНЫЙ ОТЧЕТ ОТЛАДКИ\n\n"
    
    if employees:
        report += f"✅ Сотрудников в БД: {len(employees)}\n"
        for emp in employees:
            report += f"   👤 {emp[1]} (ID: {emp[0]}, Должность: {emp[2] or 'не указана'})\n"
    else:
        report += "❌ Сотрудников в БД: 0\n"
    
    if tables:
        table_names = [table[0] for table in tables]
        report += f"✅ Таблицы в БД: {', '.join(table_names)}\n"
    else:
        report += "❌ Таблицы в БД: не найдены\n"
    
    if employees_table:
        report += f"✅ Структура таблицы employees: {len(employees_table)} колонок\n"
    
    # Проверяем последние операции
    report += "\n📊 ПРОВЕРКА ОПЕРАЦИЙ:\n"
    
    # Тестовый запрос на вставку
    test_result = execute_query(
        "INSERT INTO employees (full_name, position) VALUES (%s, %s) RETURNING id",
        ('ТЕСТОВЫЙ_СОТРУДНИК', 'тест'),
        fetch=True
    )
    
    if test_result:
        test_id = test_result[0][0]
        report += f"✅ Тестовая вставка: УСПЕШНО (ID: {test_id})\n"
        
        # Удаляем тестовую запись
        execute_query("DELETE FROM employees WHERE id = %s", (test_id,))
        report += "✅ Тестовая запись удалена\n"
    else:
        report += "❌ Тестовая вставка: ОШИБКА\n"
    
    bot.send_message(message.chat.id, report)
    logger.info("✅ Детальный отчет отладки отправлен")

def show_main_menu(chat_id):
    menu_text = "🏠 ГЛАВНОЕ МЕНЮ\n\nВыберите действие:"
    bot.send_message(chat_id, menu_text, reply_markup=create_main_menu())

def show_employees_menu(chat_id):
    menu_text = "👥 УПРАВЛЕНИЕ СОТРУДНИКАМИ\n\nВыберите действие:"
    bot.send_message(chat_id, menu_text, reply_markup=create_employees_menu())

def show_reports_menu(chat_id):
    menu_text = "📊 ОТЧЕТЫ\n\nВыберите тип отчета:"
    bot.send_message(chat_id, menu_text, reply_markup=create_reports_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    
    logger.debug(f"📨 Сообщение от {user_id}: {text}")
    
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
    
    logger.debug(f"🔄 Обработка состояния {state} для пользователя {user_id}")
    
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
        
        logger.info(f"🎯 ДОБАВЛЕНИЕ СОТРУДНИКА: {employee_name}, должность: {position}")
        
        # ВАЖНО: Добавляем RETURNING id чтобы убедиться, что запись вставилась
        result = execute_query(
            'INSERT INTO employees (full_name, position) VALUES (%s, %s) RETURNING id',
            (employee_name, position),
            fetch=True
        )
        
        logger.info(f"🎯 РЕЗУЛЬТАТ ДОБАВЛЕНИЯ: {result}")
        
        if result:
            employee_id = result[0][0]
            position_text = f"💼 {position}" if position else "💼 Должность не указана"
            bot.send_message(chat_id, 
                f"✅ СОТРУДНИК ДОБАВЛЕН!\n\n"
                f"👤 Имя: {employee_name}\n"
                f"{position_text}\n"
                f"🆔 ID в БД: {employee_id}")
            logger.info(f"✅ Успешно добавлен сотрудник: {employee_name} (ID: {employee_id})")
            
            # СРАЗУ проверяем, что сотрудник действительно есть в БД
            check_employee = execute_query(
                'SELECT * FROM employees WHERE id = %s', 
                (employee_id,), 
                fetch=True
            )
            logger.info(f"🔍 ПРОВЕРКА СОТРУДНИКА ПОСЛЕ ДОБАВЛЕНИЯ: {check_employee}")
        else:
            bot.send_message(chat_id, "❌ Ошибка при добавлении сотрудника")
            logger.error(f"❌ Ошибка добавления сотрудника: {employee_name}")
        
        # Очищаем временные данные
        del user_states[user_id]
        if f'{user_id}_name' in user_states:
            del user_states[f'{user_id}_name']
        
        show_employees_menu(chat_id)

def add_employee_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_employee_name'
    bot.send_message(chat_id,
        "👤 ДОБАВЛЕНИЕ СОТРУДНИКА\n\n"
        "Введите ФИО сотрудника:",
        reply_markup=create_cancel_menu()
    )

def view_employees(message):
    logger.info("🔍 ЗАПРОС СПИСКА СОТРУДНИКОВ...")
    employees = execute_query(
        'SELECT id, full_name, position, is_active FROM employees ORDER BY is_active DESC, full_name', 
        fetch=True
    )
    
    logger.info(f"🔍 РЕЗУЛЬТАТ ЗАПРОСА СОТРУДНИКОВ: {employees}")
    
    if not employees:
        bot.send_message(message.chat.id, "❌ Сотрудники не найдены")
        logger.warning("⚠️ В базе нет сотрудников при запросе списка")
        return
    
    text = "👥 СПИСОК СОТРУДНИКОВ\n\n"
    for emp in employees:
        emp_id, full_name, position, is_active = emp
        status = "✅" if is_active else "❌"
        position_text = f"💼 {position}" if position else "💼 Должность не указана"
        text += f"{status} {full_name}\n{position_text}\n🆔 ID: {emp_id}\n\n"
    
    bot.send_message(message.chat.id, text)
    logger.info(f"✅ Показан список из {len(employees)} сотрудников")

# Остальные функции остаются без изменений...
def mark_attendance_today(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    user_states[user_id] = 'waiting_mark_employee'
    
    employees_keyboard = create_employees_keyboard()
    if not employees_keyboard:
        bot.send_message(chat_id, "❌ Нет сотрудников для отметки")
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

def show_help(message):
    help_text = """ℹ️ ПОМОЩЬ - СИСТЕМА УЧЕТА РАБОЧЕГО ВРЕМЕНИ

👥 СОТРУДНИКИ:
• Добавление новых сотрудников
• Просмотр списка всех сотрудников

✅ ОТМЕТКА ПРИСУТСТВИЯ:
• Отметка за сегодняшний день
• Отметка за любую прошлую дату

📊 ОТЧЕТЫ:
• Общая статистика
• Отчет по сотруднику  
• Отчеты за период

💾 ХРАНЕНИЕ ДАННЫХ:
• Данные сохраняются в PostgreSQL
• Надежное хранение на сервере

🔧 ОТЛАДКА:
• Используйте /debug для проверки БД"""
    
    bot.send_message(message.chat.id, help_text)

def run_bot():
    """Запуск бота с обработкой ошибок"""
    logger.info("🚀 ЗАПУСК БОТА...")
    
    # Ждем инициализации
    time.sleep(10)
    
    if init_db():
        logger.info("✅ Бот готов к работе!")
        
        # Запускаем Flask в отдельном потоке
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        logger.info("✅ Flask сервер запущен")
        
        # Ждем еще немного перед запуском бота
        time.sleep(5)
        
        # Запускаем бота с обработкой ошибок
        while True:
            try:
                logger.info("🔄 Запуск polling...")
                bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
            except Exception as e:
                logger.error(f"❌ Ошибка бота: {e}")
                logger.info("🔄 Перезапуск через 15 секунд...")
                time.sleep(15)
    else:
        logger.error("❌ Не удалось инициализировать базу данных")
        # Пытаемся перезапуститься через 30 секунд
        time.sleep(30)
        run_bot()

if __name__ == '__main__':
    run_bot()
