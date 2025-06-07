import sqlite3
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Dict, Optional, Union
from config import DB_FILE

# Настройка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


# ================ DATACLASSES ================
@dataclass
class ArbitrageSignal:
    symbol: str
    spot_price: float
    futures_price: float
    spread_percent: float
    volume: float
    timestamp: Optional[str] = None
    id: Optional[int] = None


@dataclass
class UserSettings:
    user_id: int
    min_spread: float = 0.7
    min_volume: float = 0
    links_enabled: bool = True
    notifications_enabled: bool = True


# ================ DATABASE CONTEXT MANAGER ================
@contextmanager
def db_connection():
    """Контекстный менеджер для безопасного подключения к БД"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE, timeout=15)
        conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()


def with_cursor(func):
    """Декоратор для автоматического управления курсором"""

    def wrapper(conn, *args, **kwargs):
        cursor = conn.cursor()
        try:
            return func(cursor, *args, **kwargs)
        finally:
            cursor.close()

    return wrapper


# ================ DATABASE INITIALIZATION ================
def init_db():
    """Инициализация БД с обработкой ошибок"""
    try:
        with db_connection() as conn:
            with conn:
                # Таблица сигналов
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS arbitrage_signals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        spot_price REAL NOT NULL,
                        futures_price REAL NOT NULL,
                        spread_percent REAL NOT NULL,
                        volume REAL NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Индексы для быстрого поиска
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_signals_symbol 
                    ON arbitrage_signals(symbol)
                ''')
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_signals_timestamp 
                    ON arbitrage_signals(timestamp DESC)
                ''')

                # Таблица подписчиков
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS subscribers (
                        user_id INTEGER PRIMARY KEY
                    )
                ''')

                # Таблица настроек пользователя
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS user_settings (
                        user_id INTEGER PRIMARY KEY,
                        min_spread REAL DEFAULT 0.7,
                        min_volume REAL DEFAULT 0,
                        links_enabled INTEGER DEFAULT 1,
                        notifications_enabled INTEGER DEFAULT 1
                    )
                ''')

                # Таблица для управления миграциями
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS migrations (
                        id INTEGER PRIMARY KEY,
                        name TEXT UNIQUE NOT NULL,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

            logger.info("Database initialized successfully")

            # Применяем миграции после инициализации
            apply_migrations()

    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
        raise


# ================ MIGRATION SYSTEM ================
MIGRATIONS = [
    {
        'name': 'add_volume_column',
        'sql': "ALTER TABLE arbitrage_signals ADD COLUMN volume REAL DEFAULT 0",
        'check': lambda conn: not column_exists(conn, "arbitrage_signals", "volume")
    },
    # Пример будущей миграции:
    # {
    #     'name': 'add_exchange_column',
    #     'sql': "ALTER TABLE arbitrage_signals ADD COLUMN exchange TEXT DEFAULT 'MEXC'",
    #     'check': lambda conn: not column_exists(conn, "arbitrage_signals", "exchange")
    # }
]


def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Проверка существования колонки в таблице"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row['name'] for row in cursor.fetchall()]
    return column_name in columns


def apply_migrations():
    """Система управляемых миграций"""
    try:
        with db_connection() as conn:
            with conn:
                # Проверяем, применена ли миграция
                applied_migrations = {row['name'] for row in
                                      conn.execute("SELECT name FROM migrations").fetchall()}

                for migration in MIGRATIONS:
                    if migration['name'] not in applied_migrations:
                        if migration['check'](conn):
                            conn.execute(migration['sql'])
                            conn.execute(
                                "INSERT INTO migrations (name) VALUES (?)",
                                (migration['name'],)
                            )
                            logger.info(f"Applied migration: {migration['name']}")

    except sqlite3.Error as e:
        logger.error(f"Migration failed: {e}")
        raise


# ================ SIGNAL OPERATIONS ================
def save_signal(signal: Union[ArbitrageSignal, Dict]) -> bool:
    """Сохранить арбитражный сигнал в базу"""
    try:
        # Извлекаем значения в зависимости от типа сигнала
        if isinstance(signal, ArbitrageSignal):
            symbol = signal.symbol
            spot_price = signal.spot_price
            futures_price = signal.futures_price
            spread_percent = signal.spread_percent
            volume = signal.volume
        elif isinstance(signal, dict):
            symbol = signal['symbol']
            spot_price = signal['spot_price']
            futures_price = signal['futures_price']
            spread_percent = signal['spread_percent']
            volume = signal['volume']
        else:
            logger.error(f"Неподдерживаемый тип сигнала: {type(signal)}")
            return False

        with db_connection() as conn:
            with conn:
                conn.execute('''
                    INSERT INTO arbitrage_signals 
                    (symbol, spot_price, futures_price, spread_percent, volume)
                    VALUES (?, ?, ?, ?, ?)
                ''', (symbol, spot_price, futures_price, spread_percent, volume))
                return True
    except KeyError as e:
        logger.error(f"Отсутствует ключ в словаре сигнала: {e}")
        return False
    except sqlite3.Error as e:
        logger.error(f"Ошибка сохранения сигнала {symbol if 'symbol' in locals() else 'неизвестный'}: {e}")
        return False


def get_recent_signals(limit: int = 10) -> List[ArbitrageSignal]:
    """Получить последние сигналы"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arbitrage_signals 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))

            return [ArbitrageSignal(
                id=row['id'],
                symbol=row['symbol'],
                spot_price=row['spot_price'],
                futures_price=row['futures_price'],
                spread_percent=row['spread_percent'],
                volume=row['volume'],
                timestamp=row['timestamp']
            ) for row in cursor.fetchall()]

    except sqlite3.Error as e:
        logger.error(f"Error fetching signals: {e}")
        return []


# ================ SUBSCRIBER MANAGEMENT ================
def add_subscriber(user_id: int) -> bool:
    """Добавить пользователя в подписчики"""
    try:
        with db_connection() as conn:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO subscribers (user_id) VALUES (?)",
                    (user_id,)
                )
                return conn.total_changes > 0
    except sqlite3.Error as e:
        logger.error(f"Error adding subscriber {user_id}: {e}")
        return False


def remove_subscriber(user_id: int) -> bool:
    """Удалить пользователя из подписчиков"""
    try:
        with db_connection() as conn:
            with conn:
                conn.execute(
                    "DELETE FROM subscribers WHERE user_id = ?",
                    (user_id,)
                )
                return conn.total_changes > 0
    except sqlite3.Error as e:
        logger.error(f"Error removing subscriber {user_id}: {e}")
        return False


def get_subscribers() -> List[int]:
    """Получить список всех подписчиков"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM subscribers")
            return [row['user_id'] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Error getting subscribers: {e}")
        return []


# ================ USER SETTINGS ================
def get_user_settings(user_id: int) -> UserSettings:
    """Получить настройки пользователя"""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT min_spread, min_volume, links_enabled, notifications_enabled 
                FROM user_settings WHERE user_id = ?
            ''', (user_id,))

            row = cursor.fetchone()
            if row:
                return UserSettings(
                    user_id=user_id,
                    min_spread=row['min_spread'],
                    min_volume=row['min_volume'],
                    links_enabled=bool(row['links_enabled']),
                    notifications_enabled=bool(row['notifications_enabled'])
                )

    except sqlite3.Error as e:
        logger.error(f"Error getting settings for user {user_id}: {e}")

    # Возвращаем настройки по умолчанию
    return UserSettings(user_id=user_id)


def save_user_settings(settings: UserSettings) -> bool:
    """Сохранить настройки пользователя"""
    try:
        with db_connection() as conn:
            with conn:
                conn.execute('''
                    INSERT INTO user_settings 
                    (user_id, min_spread, min_volume, links_enabled, notifications_enabled)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        min_spread = excluded.min_spread,
                        min_volume = excluded.min_volume,
                        links_enabled = excluded.links_enabled,
                        notifications_enabled = excluded.notifications_enabled
                ''', (
                    settings.user_id,
                    settings.min_spread,
                    settings.min_volume,
                    int(settings.links_enabled),
                    int(settings.notifications_enabled)
                ))
                return True
    except sqlite3.Error as e:
        logger.error(f"Error saving settings for user {settings.user_id}: {e}")
        return False


# ================ MAINTENANCE OPERATIONS ================
def optimize_db():
    """Оптимизация размера базы данных"""
    try:
        with db_connection() as conn:
            with conn:
                conn.execute("VACUUM")
                conn.execute("PRAGMA optimize")
                logger.info("Database optimization completed")
                return True
    except sqlite3.Error as e:
        logger.error(f"Database optimization failed: {e}")
        return False


def cleanup_old_data(days: int = 30):
    """Очистка старых данных"""
    try:
        with db_connection() as conn:
            with conn:
                conn.execute('''
                    DELETE FROM arbitrage_signals 
                    WHERE timestamp < datetime('now', ?)
                ''', (f'-{days} days',))
                logger.info(f"Cleaned up data older than {days} days")
                return True
    except sqlite3.Error as e:
        logger.error(f"Data cleanup failed: {e}")
        return False


if __name__ == "__main__":
    # Инициализация и пример использования
    init_db()

    # Пример работы с новым интерфейсом
    signal = ArbitrageSignal(
        symbol="BTCUSDT",
        spot_price=50000.0,
        futures_price=50250.0,
        spread_percent=0.5,
        volume=1500000.0
    )

    if save_signal(signal):
        print("Signal saved successfully")

    # Тест работы со словарем
    signal_dict = {
        'symbol': "ETHUSDT",
        'spot_price': 3500.0,
        'futures_price': 3520.0,
        'spread_percent': 0.57,
        'volume': 2000000.0
    }

    if save_signal(signal_dict):
        print("Dictionary signal saved successfully")

    user_settings = get_user_settings(123)
    user_settings.min_spread = 1.0
    save_user_settings(user_settings)

    # Плановое обслуживание
    cleanup_old_data()
    optimize_db()
