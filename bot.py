import os
import logging
import sqlite3
import pandas as pd
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Состояния для ConversationHandler
WAITING_FOR_NAME, WAITING_FOR_POSITION = range(2)

# Путь к базе данных
DB_PATH = os.path.join(os.getcwd(), 'data', 'attendance.db')

# Инициализация базы данных
def init_db():
    # Создаем папку data если её нет
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица сотрудников
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
    
    # Таблица посещаемости
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
    
    # Таблица администраторов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# Проверка прав администратора
def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Автоматическая регистрация пользователя Telegram как сотрудника
def register_telegram_user(user_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM employees WHERE telegram_id = ?', (user_id,))
    existing = cursor.fetchone()
    
    if not existing:
        cursor.execute('''
            INSERT INTO employees (full_name, position, telegram_id) 
            VALUES (?, ?, ?)
        ''', (full_name, "Сотрудник", user_id))
        logger.info(f"Зарегистрирован новый сотрудник: {full_name} (ID: {user_id})")
    
    conn.commit()
    conn.close()

# Команда старт
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    await update.message.reply_text(
        f"Привет, {full_name}! 👋\n"
        "Я бот для учета рабочего времени.\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

# Обработка нажатий кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "check_in":
        await check_in(query, context)
    elif data == "my_report":
        await my_report(query, context)
    elif data == "manage_employees":
        if is_admin(user_id):
            await manage_employees(query, context)
        else:
            await query.edit_message_text("❌ У вас нет прав для этого действия")
    elif data == "export_report":
        if is_admin(user_id):
            await export_report(query, context)
        else:
            await query.edit_message_text("❌ У вас нет прав для этого действия")
    elif data == "add_employee_menu":
        await add_employee_menu(query, context)
    elif data == "add_employee_with_telegram":
        await query.edit_message_text(
            "Для добавления сотрудника с привязкой к Telegram отправьте его Telegram ID.\n"
            "Попросите сотрудника написать @userinfobot чтобы узнать его ID."
        )
        context.user_data['waiting_for_telegram_id'] = True
    elif data == "add_employee_without_telegram":
        await query.edit_message_text("Введите ФИО сотрудника:")
        return WAITING_FOR_NAME
    elif data == "view_employees":
        await view_employees(query, context)
    elif data == "back_to_menu":
        await show_main_menu(query, context)
    elif data == "back_to_manage":
        await manage_employees(query, context)

# Меню добавления сотрудника
async def add_employee_menu(query, context):
    keyboard = [
        [InlineKeyboardButton("📱 С привязкой к Telegram", callback_data="add_employee_with_telegram")],
        [InlineKeyboardButton("👤 Просто по имени (без Telegram)", callback_data="add_employee_without_telegram")],
        [InlineKeyboardButton("🔙 Назад", callback_data="manage_employees")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👥 Добавление сотрудника:\nВыберите тип добавления:",
        reply_markup=reply_markup
    )

# Отметка присутствия
async def check_in(query, context):
    user_id = query.from_user.id
    today = date.today().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM employees WHERE telegram_id = ?', (user_id,))
    employee = cursor.fetchone()
    
    if not employee:
        await query.edit_message_text("❌ Вы не зарегистрированы как сотрудник!")
        conn.close()
        return
    
    employee_id = employee[0]
    
    cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND check_date = ?', (employee_id, today))
    
    if cursor.fetchone():
        await query.edit_message_text("✅ Вы уже отметили свое присутствие сегодня!")
    else:
        cursor.execute('INSERT INTO attendance (employee_id, check_date) VALUES (?, ?)', (employee_id, today))
        conn.commit()
        await query.edit_message_text("✅ Присутствие успешно отмечено!")
        logger.info(f"Сотрудник {employee_id} отметил присутствие")
    
    conn.close()

# Просмотр личного отчета
async def my_report(query, context):
    user_id = query.from_user.id
    conn = sqlite3.connect(DB_PATH)
    
    employee_info = pd.read_sql_query(
        'SELECT id, full_name, position, registered_date FROM employees WHERE telegram_id = ?', 
        conn, params=(user_id,)
    )
    
    if employee_info.empty:
        await query.edit_message_text("❌ Вы не зарегистрированы как сотрудник!")
        conn.close()
        return
    
    employee_id = employee_info.iloc[0]['id']
    
    attendance_data = pd.read_sql_query(
        'SELECT check_date, check_time FROM attendance WHERE employee_id = ? ORDER BY check_date DESC LIMIT 30', 
        conn, params=(employee_id,)
    )
    
    conn.close()
    
    full_name = employee_info.iloc[0]['full_name']
    position = employee_info.iloc[0]['position'] or "Не указана"
    registered_date = employee_info.iloc[0]['registered_date']
    
    report_text = f"📊 Отчет по сотруднику:\n\n👤 Имя: {full_name}\n💼 Должность: {position}\n📅 Зарегистрирован: {registered_date[:10]}\n\n📈 Последние отметки ({len(attendance_data)}):\n"
    
    for _, row in attendance_data.iterrows():
        report_text += f"✅ {row['check_date']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(report_text, reply_markup=reply_markup)

# Управление сотрудниками
async def manage_employees(query, context):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить сотрудника", callback_data="add_employee_menu")],
        [InlineKeyboardButton("👥 Список сотрудников", callback_data="view_employees")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("👥 Управление сотрудниками:\nВыберите действие:", reply_markup=reply_markup)

# Просмотр списка сотрудников
async def view_employees(query, context):
    conn = sqlite3.connect(DB_PATH)
    employees = pd.read_sql_query(
        'SELECT id, full_name, position, telegram_id, is_active, registered_date FROM employees ORDER BY is_active DESC, full_name', 
        conn
    )
    conn.close()
    
    if employees.empty:
        text = "❌ Сотрудники не найдены"
    else:
        text = "👥 Список сотрудников:\n\n"
        for _, emp in employees.iterrows():
            status = "✅" if emp['is_active'] else "❌"
            telegram_info = f"📱 ID: {emp['telegram_id']}" if emp['telegram_id'] else "👤 Без Telegram"
            text += f"{status} {emp['full_name']}\n💼 {emp['position'] or 'Не указана'}\n{telegram_info}\n📅 {emp['registered_date'][:10]}\nID в системе: {emp['id']}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="manage_employees")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

# Обработка добавления сотрудника по имени
async def receive_employee_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    employee_name = update.message.text
    context.user_data['new_employee_name'] = employee_name
    await update.message.reply_text(f"Отлично! Сотрудник: {employee_name}\nТеперь введите должность сотрудника:")
    return WAITING_FOR_POSITION

async def receive_employee_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    position = update.message.text
    employee_name = context.user_data['new_employee_name']
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO employees (full_name, position) VALUES (?, ?)', (employee_name, position))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Сотрудник успешно добавлен!\n👤 Имя: {employee_name}\n💼 Должность: {position}\n📝 Тип: Без привязки к Telegram")
    context.user_data.pop('new_employee_name', None)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добавление сотрудника отменено.")
    context.user_data.pop('new_employee_name', None)
    return ConversationHandler.END

# Обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if context.user_data.get('waiting_for_telegram_id') and is_admin(user_id):
        try:
            telegram_id = int(update.message.text)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM employees WHERE telegram_id = ?', (telegram_id,))
            if cursor.fetchone():
                await update.message.reply_text("❌ Этот сотрудник уже добавлен!")
            else:
                cursor.execute('INSERT INTO employees (full_name, position, telegram_id) VALUES (?, ?, ?)', (f"Сотрудник {telegram_id}", "Сотрудник", telegram_id))
                conn.commit()
                await update.message.reply_text(f"✅ Сотрудник с Telegram ID {telegram_id} успешно добавлен!")
                logger.info(f"Добавлен сотрудник с Telegram ID: {telegram_id}")
            
            conn.close()
            context.user_data['waiting_for_telegram_id'] = False
            
        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, введите корректный ID (только цифры)")
    else:
        await update.message.reply_text("Используйте кнопки меню для навигации")

# Выгрузка отчета в Excel
async def export_report(query, context):
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("❌ У вас нет прав для этого действия")
        return
        
    conn = sqlite3.connect(DB_PATH)
    
    try:
        report_data = pd.read_sql_query('''
            SELECT e.full_name, e.position, e.telegram_id, a.check_date, a.check_time, a.status
            FROM attendance a JOIN employees e ON a.employee_id = e.id
            ORDER BY a.check_date DESC, e.full_name
        ''', conn)
        
        if report_data.empty:
            await query.edit_message_text("❌ Нет данных для отчета")
            return
        
        from io import BytesIO
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            report_data.to_excel(writer, sheet_name='Посещаемость', index=False)
            
            if not report_data.empty:
                pivot = pd.pivot_table(report_data, values='check_date', index='full_name', columns='check_date', aggfunc='count', fill_value=0)
                pivot.to_excel(writer, sheet_name='Сводка')
            
            stats = report_data.groupby('full_name').agg({'check_date': 'count'}).rename(columns={'check_date': 'Дней отработано'})
            stats.to_excel(writer, sheet_name='Статистика')
        
        output.seek(0)
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=output,
            filename=f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            caption="📊 Отчет по посещаемости сотрудников"
        )
        
        await query.edit_message_text("✅ Отчет успешно сгенерирован и отправлен!")
        logger.info("Сгенерирован отчет Excel")
        
    except Exception as e:
        logger.error(f"Ошибка при создании отчета: {e}")
        await query.edit_message_text("❌ Ошибка при создании отчета")
    finally:
        conn.close()

# Главное меню
async def show_main_menu(query, context):
    user_id = query.from_user.id
    
    keyboard = [
        [InlineKeyboardButton("📝 Отметить присутствие", callback_data="check_in")],
        [InlineKeyboardButton("📊 Мой отчет", callback_data="my_report")],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👥 Управление сотрудниками", callback_data="manage_employees")])
        keyboard.append([InlineKeyboardButton("📋 Выгрузить отчет", callback_data="export_report")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("Главное меню:\nВыберите действие:", reply_markup=reply_markup)

# Основная функция
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return
    
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u, c: WAITING_FOR_NAME, pattern='^add_employee_without_telegram$')],
        states={
            WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_employee_name)],
            WAITING_FOR_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_employee_position)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    logger.info("🤖 Бот запущен на Railway!")
    application.run_polling()

if __name__ == '__main__':
    main()
