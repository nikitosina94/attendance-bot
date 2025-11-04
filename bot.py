import os
import logging
import sys
import time
from datetime import date, datetime, timedelta

# Настройка логирования ДО всех импортов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),  # Вывод в консоль Render
        logging.StreamHandler(sys.stderr)   # Вывод ошибок
    ]
)
logger = logging.getLogger(__name__)

def check_environment():
    """Проверяем все необходимые переменные окружения"""
    logger.info("🔍 Проверка переменных окружения...")
    
    required_vars = ['BOT_TOKEN', 'DATABASE_URL', 'ADMIN_ID']
    missing_vars = []
    
    for var in required_vars:
        value = os.environ.get(var)
        if not value:
            missing_vars.append(var)
            logger.error(f"❌ Отсутствует {var}")
        else:
            logger.info(f"✅ {var} установлен")
    
    if missing_vars:
        logger.error(f"❌ Отсутствуют переменные: {missing_vars}")
        return False
    
    return True

# Проверяем переменные ДО импортов
if not check_environment():
    sys.exit(1)

# Теперь импортируем остальные модули
try:
    import psycopg
    import telebot
    from telebot import types
    logger.info("✅ Все модули успешно импортированы")
except ImportError as e:
    logger.error(f"❌ Ошибка импорта модулей: {e}")
    sys.exit(1)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')
ADMIN_ID = os.environ.get('ADMIN_ID')

logger.info(f"🔄 Инициализация бота...")

try:
    bot = telebot.TeleBot(BOT_TOKEN)
    logger.info("✅ Бот успешно инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации бота: {e}")
    sys.exit(1)

user_states = {}

def get_connection():
    """Создает соединение с PostgreSQL"""
    try:
        logger.info(f"🔗 Попытка подключения к PostgreSQL...")
        conn = psycopg.connect(DATABASE_URL)
        logger.info("✅ Успешное подключение к PostgreSQL")
        return conn
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        return None

def init_db():
    """Инициализация таблиц"""
    logger.info("🔄 Инициализация базы данных...")
    
    conn = get_connection()
    if not conn:
        logger.error("❌ Не удалось подключиться к базе данных")
        return False
    
    try:
        with conn.cursor() as cursor:
            logger.info("🔧 Создание таблиц...")
            
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
                    check_date DATE,
                    marked_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("✅ Таблица attendance создана/проверена")
            
            # Таблица администраторов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER UNIQUE
                )
            ''')
            logger.info("✅ Таблица admins создана/проверена")
            
            # Добавляем администратора
            if ADMIN_ID:
                cursor.execute(
                    'INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING', 
                    (int(ADMIN_ID),)
                )
                logger.info(f"✅ Администратор {ADMIN_ID} добавлен")
            
            conn.commit()
            logger.info("✅ База данных успешно инициализирована")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def execute_query(query, params=None, fetch=False):
    """Универсальная функция выполнения запросов"""
    conn = get_connection()
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

@bot.message_handler(commands=['start', 'test'])
def start(message):
    logger.info(f"👤 Пользователь {message.from_user.id} запустил бота")
    
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ У вас нет доступа к этому боту")
        return
    
    # Простое меню для теста
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("👥 Сотрудники", "✅ Отметить")
    keyboard.add("📊 Отчет", "🔄 Статус")
    
    bot.send_message(
        message.chat.id,
        "🏠 Бот для учета рабочего времени\n\nБот успешно запущен!",
        reply_markup=keyboard
    )

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text
    
    logger.info(f"📨 Сообщение от {user_id}: {text}")
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Нет доступа")
        return
    
    if text == "👥 Сотрудники":
        show_employees(message)
    elif text == "✅ Отметить":
        mark_attendance(message)
    elif text == "📊 Отчет":
        show_report(message)
    elif text == "🔄 Статус":
        show_status(message)
    else:
        bot.send_message(message.chat.id, "Используйте кнопки меню")

def show_employees(message):
    result = execute_query('SELECT COUNT(*) FROM employees', fetch=True)
    if result is None:
        bot.send_message(message.chat.id, "❌ Ошибка базы данных")
        return
    
    count = result[0][0]
    bot.send_message(message.chat.id, f"👥 Всего сотрудников: {count}")

def mark_attendance(message):
    today = date.today().strftime('%d.%m.%Y')
    bot.send_message(message.chat.id, f"✅ Отметка за {today}")

def show_report(message):
    employees_count = execute_query('SELECT COUNT(*) FROM employees', fetch=True)
    attendance_count = execute_query('SELECT COUNT(*) FROM attendance', fetch=True)
    
    if employees_count is None or attendance_count is None:
        bot.send_message(message.chat.id, "❌ Ошибка получения данных")
        return
    
    report = f"📊 Отчет:\nСотрудников: {employees_count[0][0]}\nОтметок: {attendance_count[0][0]}"
    bot.send_message(message.chat.id, report)

def show_status(message):
    # Проверяем соединение с базой
    start_time = time.time()
    result = execute_query('SELECT 1, NOW()', fetch=True)
    end_time = time.time()
    
    if result:
        response_time = round((end_time - start_time) * 1000, 2)
        status = f"✅ Бот работает\n⚡ Ответ БД: {response_time}ms\n🐍 Python: {sys.version.split()[0]}"
    else:
        status = "❌ Проблемы с базой данных"
    
    bot.send_message(message.chat.id, status)

def main():
    """Основная функция запуска"""
    logger.info("🚀 ЗАПУСК БОТА...")
    
    # Даем время на пробуждение базы
    logger.info("⏳ Ожидание инициализации...")
    time.sleep(5)
    
    # Инициализируем базу
    if not init_db():
        logger.error("❌ Критическая ошибка: не удалось инициализировать БД")
        return
    
    # Запускаем бота
    logger.info("🤖 ЗАПУСК POLLING...")
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"❌ Ошибка в работе бота: {e}")

if __name__ == '__main__':
    main()
