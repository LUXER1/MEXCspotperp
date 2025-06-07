# config.py (оптимизированная версия)
import os

# --- Telegram ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", )
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", ))
THREAD_ID = 42

# --- Thresholds ---
THRESHOLD_PERCENT = 1.5  # Минимальный спред для логирования
THRESHOLD_NOTIFY_PERCENT = 2.0  # Спред для отправки уведомлений
RISK_MULTIPLIER = 3  # Множитель для расчета плеча

# --- Интервалы ---
CHECK_INTERVAL_FAST = 30  # Для топ-50 пар
CHECK_INTERVAL_SLOW = 120  # Для остальных пар
PAIRS_UPDATE_INTERVAL = 3600  # Обновление списка пар каждый час

# Лимиты
TOP_VOLUME_LIMIT = 100  # Количество пар для мониторинга
API_RATE_LIMIT = 20  # Макс. запросов в секунду
API_MAX_CONCURRENT_REQUESTS = 10  # Параллельных запросов

# --- WebSocket ---
MEXC_SPOT_WS_URL = [
    "wss://wbs.mexc.com/ws",
    "wss://wbs-backup.mexc.com/ws"
]

# --- База данных ---
DB_FILE = "arbitrage.db"
DB_ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY")  # Для SQLite с шифрованием

# --- Режимы ---
DEBUG = True
DRY_RUN = True  # Тестовый режим без сделок
