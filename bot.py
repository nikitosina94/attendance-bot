import os
import logging
import sqlite3
import csv
import io
from datetime import datetime, date

# Импорты для python-telegram-bot 13.7
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
DB_PATH = 'attendance.db'

# Состояния для ConversationHandler
WAITING_FOR_NAME, WAITING_FOR_POSITION = range(2)

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
            status TEXT DEFAULT 'present',
            FOREIGN KEY (employee_id) REFERENCES employees (id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT
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

def register_telegram_user(user_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM employees WHERE telegram_id = ?', (user_id,))
    existing = cursor.fetchone()
    
    if not existing:
        cursor.execute('INSERT INTO employees (full_name, position, telegram_id) VALUES (?, ?, ?)', 
                      (full_name, "Сотрудник", user_id))
        logger.info(f"Зарегистрирован новый сотрудник: {full_name}")
    
    conn.commit()
    conn.close()

def start(update, context):
    user_id = update.effective_user.id
    username = update.effective_user.username
    full_name = update.effective_user.full_name
    
    register_telegram_user(user_id, username, full_name)
    
    keyboard = [
        [InlineKeyboardButton("📝 Отметить присутствие", callback_data="check_in")],
        [InlineKeyboardButton("📊 Мой отчет", callback_data="my_report")],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👥 Управление сотрудниками", callback_data="manage_employees")])
        keyboard.append([InlineKeyboardButton("📋 Выгрузить отчет", callback_data="export_report")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        f"Привет, {full_name}! 👋\nЯ бот для учета рабочего времени.\nВыберите действие:",
        reply_markup=reply_markup
    )

def button_handler(update, context):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "check_in":
        check_in(query, context)
    elif data == "my_report":
        my_report(query, context)
    elif data == "manage_employees":
        if is_admin(user_id):
            manage_employees(query, context)
        else:
            query.edit_message_text("❌ У вас нет прав для этого действия")
    elif data == "export_report":
        if is_admin(user_id):
            export_report(query, context)
        else:
            query.edit_message_text("❌ У вас нет прав для этого действия")
    elif data == "add_employee_menu":
        add_employee_menu(query, context)
    elif data == "add_employee_with_telegram":
        query.edit_message_text("Отправьте Telegram ID сотрудника:")
        context.user_data['waiting_for_telegram_id'] = True
    elif data == "add_employee_without_telegram":
        query.edit_message_text("Введите ФИО сотрудника:")
        return WAITING_FOR_NAME
    elif data == "view_employees":
        view_employees(query, context)
    elif data == "back_to_menu":
        show_main_menu(query, context)
    elif data == "back_to_manage":
        manage_employees(query, context)

def add_employee_menu(update, context):
    query = update
    keyboard = [
        [InlineKeyboardButton("📱 С привязкой к Telegram", callback_data="add_employee_with_telegram")],
        [InlineKeyboardButton("👤 Просто по имени", callback_data="add_employee_without_telegram")],
        [InlineKeyboardButton("🔙 Назад", callback_data="manage_employees")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("👥 Добавление сотрудника:", reply_markup=reply_markup)

def check_in(update, context):
    query = update
    user_id = query.from_user.id
    today = date.today().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if not employee:
        query.edit_message_text("❌ Вы не зарегистрированы как сотрудник!")
        conn.close()
        return
    
    employee_id = employee[0]
    
    cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND check_date = ?', (employee_id, today))
    
    if cursor.fetchone():
        query.edit_message_text("✅ Вы уже отметили присутствие сегодня!")
    else:
        cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', (employee_id, today))
        conn.commit()
        query.edit_message_text("✅ Присутствие успешно отмечено!")
        logger.info(f"Сотрудник {employee_id} отметил присутствие")
    
    conn.close()

def my_report(update, context):
    query = update
    user_id = query.from_user.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем информацию о сотруднике
    cursor.execute('SELECT id, full_name, position, registered_date FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if not employee:
        query.edit_message_text("❌ Вы не зарегистрированы как сотрудник!")
        conn.close()
        return
    
    employee_id, full_name, position, registered_date = employee
    
    # Получаем записи о посещаемости
    cursor.execute('SELECT check_date, check_time FROM attendance WHERE employee_id = ? ORDER BY check_date DESC LIMIT 30', (employee_id,))
    attendance_records = cursor.fetchall()
    
    report_text = f"📊 Отчет по сотруднику:\n\n👤 Имя: {full_name}\n💼 Должность: {position or 'Не указана'}\n📅 Зарегистрирован: {registered_date[:10]}\n\n📈 Последние отметки ({len(attendance_records)}):\n"
    
    for record in attendance_records:
        report_text += f"✅ {record[0]}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(report_text, reply_markup=reply_markup)
    conn.close()

def manage_employees(update, context):
    query = update
    keyboard = [
        [InlineKeyboardButton("➕ Добавить сотрудника", callback_data="add_employee_menu")],
        [InlineKeyboardButton("👥 Список сотрудников", callback_data="view_employees")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("👥 Управление сотрудниками:", reply_markup=reply_markup)

def view_employees(update, context):
    query = update
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, full_name, position, telegram_id, is_active, registered_date FROM employees ORDER BY is_active DESC, full_name')
    employees = cursor.fetchall()
    
    if not employees:
        text = "❌ Сотрудники не найдены"
    else:
        text = "👥 Список сотрудников:\n\n"
        for emp in employees:
            emp_id, full_name, position, telegram_id, is_active, registered_date = emp
            status = "✅" if is_active else "❌"
            telegram_info = f"📱 ID: {telegram_id}" if telegram_id else "👤 Без Telegram"
            text += f"{status} {full_name}\n💼 {position or 'Не указана'}\n{telegram_info}\n📅 {registered_date[:10]}\nID: {emp_id}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="manage_employees")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(text, reply_markup=reply_markup)
    conn.close()

def receive_employee_name(update, context):
    employee_name = update.message.text
    context.user_data['new_employee_name'] = employee_name
    update.message.reply_text(f"Отлично! Сотрудник: {employee_name}\nТеперь введите должность:")
    return WAITING_FOR_POSITION

def receive_employee_position(update, context):
    position = update.message.text
    employee_name = context.user_data['new_employee_name']
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO employees (full_name, position) VALUES (?, ?)', (employee_name, position))
    conn.commit()
    conn.close()
    
    update.message.reply_text(f"✅ Сотрудник добавлен!\n👤 Имя: {employee_name}\n💼 Должность: {position}")
    context.user_data.pop('new_employee_name', None)
    return ConversationHandler.END

def cancel(update, context):
    update.message.reply_text("Добавление сотрудника отменено.")
    context.user_data.pop('new_employee_name', None)
    return ConversationHandler.END

def handle_message(update, context):
    user_id = update.effective_user.id
    
    if context.user_data.get('waiting_for_telegram_id') and is_admin(user_id):
        try:
            telegram_id = int(update.message.text)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM employees WHERE telegram_id = ?', (telegram_id,))
            if cursor.fetchone():
                update.message.reply_text("❌ Этот сотрудник уже добавлен!")
            else:
                cursor.execute('INSERT INTO employees (full_name, position, telegram_id) VALUES (?, ?, ?)', 
                              (f"Сотрудник {telegram_id}", "Сотрудник", telegram_id))
                conn.commit()
                update.message.reply_text(f"✅ Сотрудник с Telegram ID {telegram_id} добавлен!")
                logger.info(f"Добавлен сотрудник с Telegram ID: {telegram_id}")
            
            conn.close()
            context.user_data['waiting_for_telegram_id'] = False
            
        except ValueError:
            update.message.reply_text("❌ Введите корректный ID (только цифры)")
    else:
        update.message.reply_text("Используйте кнопки меню для навигации")

def export_report(update, context):
    query = update
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        query.edit_message_text("❌ У вас нет прав для этого действия")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Получаем данные для отчета
        cursor.execute('''
            SELECT e.full_name, e.position, e.telegram_id, a.check_date, a.check_time, a.status
            FROM attendance a 
            JOIN employees e ON a.employee_id = e.id
            ORDER BY a.check_date DESC, e.full_name
        ''')
        
        report_data = cursor.fetchall()
        
        if not report_data:
            query.edit_message_text("❌ Нет данных для отчета")
            return
        
        # Создаем CSV файл
        output = io.StringIO()
        csv_writer = csv.writer(output)
        
        # Заголовки
        csv_writer.writerow(['ФИО', 'Должность', 'Telegram ID', 'Дата', 'Время', 'Статус'])
        
        # Данные
        for row in report_data:
            csv_writer.writerow(row)
        
        # Создаем файл в памяти
        csv_data = output.getvalue().encode('utf-8')
        csv_file = io.BytesIO(csv_data)
        csv_file.name = f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        # Отправляем файл
        context.bot.send_document(
            chat_id=query.message.chat_id,
            document=csv_file,
            caption="📊 Отчет по посещаемости сотрудников (CSV)"
        )
        
        query.edit_message_text("✅ Отчет успешно сгенерирован и отправлен!")
        logger.info("Сгенерирован CSV отчет")
        
    except Exception as e:
        logger.error(f"Ошибка при создании отчета: {e}")
        query.edit_message_text("❌ Ошибка при создании отчета")
    finally:
        conn.close()

def show_main_menu(update, context):
    query = update
    user_id = query.from_user.id
    
    keyboard = [
        [InlineKeyboardButton("📝 Отметить присутствие", callback_data="check_in")],
        [InlineKeyboardButton("📊 Мой отчет", callback_data="my_report")],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👥 Управление сотрудниками", callback_data="manage_employees")])
        keyboard.append([InlineKeyboardButton("📋 Выгрузить отчет", callback_data="export_report")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Главное меню:", reply_markup=reply_markup)

def error(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return
    
    init_db()
    
    # Создаем Updater и передаем ему токен
    updater = Updater(BOT_TOKEN, use_context=True)
    
    # Получаем диспетчер для регистрации обработчиков
    dp = updater.dispatcher
    
    # ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u, c: WAITING_FOR_NAME, pattern='add_employee_without_telegram')],
        states={
            WAITING_FOR_NAME: [MessageHandler(Filters.text, receive_employee_name)],
            WAITING_FOR_POSITION: [MessageHandler(Filters.text, receive_employee_position)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Обработчики команд
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text, handle_message))
    
    # Обработчик ошибок
    dp.add_error_handler(error)
    
    # Запускаем бота
    updater.start_polling()
    logger.info("🤖 Бот запущен!")
    
    # Запускаем бота до тех пор, пока пользователь не нажмет Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()
