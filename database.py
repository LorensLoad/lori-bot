import aiosqlite

DB_PATH = "lori.db"


async def init_db():
    """Создаёт таблицы, если их ещё нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                facts TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица сообщений (история диалога)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()


async def save_message(user_id: int, role: str, content: str):
    """Сохраняет сообщение в историю."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()


async def get_history(user_id: int, limit: int = 20):
    """Возвращает последние N сообщений пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """SELECT role, content FROM messages
               WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        # Возвращаем в хронологическом порядке
        return list(reversed(rows))


async def clear_history(user_id: int):
    """Очищает историю пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_facts(user_id: int) -> str:
    """Возвращает сохранённые факты о пользователе."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT facts FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else ""


async def save_facts(user_id: int, facts: str):
    """Сохраняет факты о пользователе."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Пытаемся обновить
        await db.execute(
            """INSERT INTO users (user_id, facts) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET facts = ?""",
            (user_id, facts, facts)
        )
        await db.commit()