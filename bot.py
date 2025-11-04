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
        except psycopg.OperationalError as e:
            logger.warning(f"⚠️ Попытка {attempt + 1} не удалась: {e}")
            if attempt < max_retries - 1:
                logger.info(f"🔄 Повторная попытка через {delay} секунд...")
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"❌ Все попытки подключения не удались: {e}")
                return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка подключения: {e}")
            return None

def init_db():
    """Инициализация таблиц с повторными попытками"""
    conn = get_connection_with_retry()
    if not conn:
        logger.error("❌ Не удалось подключиться к базе данных после нескольких попыток")
        return False
    
    try:
        with conn.cursor() as cursor:
            # Проверяем соединение
            cursor.execute('SELECT 1')
            cursor.fetchone()
            
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
            logger.info("✅ Таблицы успешно созданы/проверены")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблиц: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def execute_query(query, params=None, fetch=False):
    """Универсальная функция выполнения запросов с переподключением"""
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

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ У вас нет доступа к этому боту")
        return
    
    # Проверяем соединение с базой
    test_result = execute_query('SELECT 1', fetch=True)
    if not test_result:
        bot.send_message(message.chat.id, "⚠️ Проблемы с подключением к базе данных. Попробуйте позже.")
        return
    
    # Основное меню
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "👥 Сотрудники",
        "✅ Отметить сегодня", 
        "📊 Отчеты",
        "🔄 Проверить базу"
    ]
    keyboard.add(*buttons)
    
    bot.send_message(
        message.chat.id,
        "🏠 Бот для учета рабочего времени\n\nБаза данных: ✅ подключена\nВыберите действие:",
        reply_markup=keyboard
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
    elif text == "✅ Отметить сегодня":
        mark_attendance_today(message)
    elif text == "📊 Отчеты":
        show_reports(message)
    elif text == "🔄 Проверить базу":
        check_database(message)
    else:
        bot.send_message(message.chat.id, "Используйте кнопки меню")

def show_employees_menu(message):
    result = execute_query('SELECT COUNT(*) FROM employees', fetch=True)
    if result is None:
        bot.send_message(message.chat.id, "❌ Ошибка подключения к базе")
        return
    
    count = result[0][0]
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("➕ Добавить сотрудника", "📋 Список сотрудников")
    keyboard.add("🔙 Главное меню")
    
    bot.send_message(
        message.chat.id, 
        f"👥 Управление сотрудниками\n\nВсего сотрудников: {count}",
        reply_markup=keyboard
    )

def mark_attendance_today(message):
    today = date.today()
    bot.send_message(
        message.chat.id, 
        f"✅ Отметка присутствия\n\nСегодня: {today.strftime('%d.%m.%Y')}\n\nФункция в разработке..."
    )

def show_reports(message):
    employees_count = execute_query('SELECT COUNT(*) FROM employees', fetch=True)
    attendance_count = execute_query('SELECT COUNT(*) FROM attendance', fetch=True)
    
    if employees_count is None or attendance_count is None:
        bot.send_message(message.chat.id, "❌ Ошибка получения данных")
        return
    
    report_text = f"📊 Общая статистика:\n\n"
    report_text += f"👥 Сотрудников: {employees_count[0][0]}\n"
    report_text += f"✅ Отметок: {attendance_count[0][0]}\n"
    report_text += f"📅 Дата: {date.today().strftime('%d.%m.%Y')}"
    
    bot.send_message(message.chat.id, report_text)

def check_database(message):
    """Проверка соединения с базой данных"""
    start_time = time.time()
    result = execute_query('SELECT 1 as test, NOW() as time', fetch=True)
    end_time = time.time()
    
    if result:
        db_time = result[0][1]
        response_time = round((end_time - start_time) * 1000, 2)
        
        status_text = f"✅ База данных работает\n\n"
        status_text += f"🕒 Время БД: {db_time.strftime('%H:%M:%S')}\n"
        status_text += f"⚡ Скорость ответа: {response_time}ms\n"
        status_text += f"🐍 Python: 3.13.4 + psycopg3\n"
        status_text += f"📊 Соединение: стабильное"
        
        bot.send_message(message.chat.id, status_text)
    else:
        bot.send_message(message.chat.id, "❌ Ошибка подключения к базе данных")

if __name__ == '__main__':
    logger.info("🔄 Запуск бота с psycopg3 на Python 3.13.4...")
    
    # Даем базе данных время на "пробуждение"
    logger.info("⏳ Ожидание инициализации базы данных...")
    time.sleep(5)
    
    if init_db():
        logger.info("✅ Бот успешно запущен и готов к работе!")
        try:
            bot.infinity_polling()
        except Exception as e:
            logger.error(f"❌ Ошибка в работе бота: {e}")
    else:
        logger.error("❌ Критическая ошибка: не удалось инициализировать базу данных")
