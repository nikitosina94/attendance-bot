import os
import sqlite3
import sys

def init_admin():
    # Создаем папку для данных
    os.makedirs('/data', exist_ok=True)
    
    conn = sqlite3.connect('/data/attendance.db')
    cursor = conn.cursor()
    
    # Создаем таблицы если их нет
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT
        )
    ''')
    
    # Добавляем администратора из переменной окружения
    admin_id = os.environ.get('ADMIN_ID')
    if admin_id:
        try:
            cursor.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (int(admin_id),))
            conn.commit()
            print(f"✅ Администратор {admin_id} добавлен!")
        except ValueError:
            print("❌ ADMIN_ID должен быть числом")
    else:
        print("ℹ️ ADMIN_ID не установлен")
    
    conn.close()

if __name__ == '__main__':
    init_admin()
