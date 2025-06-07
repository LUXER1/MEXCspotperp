# ==============================
# 📡 ARBITRAGE SCANNER FOR MEXC
# ==============================
# Автор: [Ваше Имя]
# Версия: 1.3
# Описание: Продвинутый мониторинг спредов с аналитикой и управлением рисками
# ==============================

import asyncio
import aiohttp
import time
import re
import logging
import json
import pytz
from datetime import datetime
from telegram.error import TimedOut
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
# 🔧 CONFIGURATION
from config import (
    THRESHOLD_PERCENT,
    THRESHOLD_NOTIFY_PERCENT,
    TELEGRAM_GROUP_ID,
    THREAD_ID,
    CHECK_INTERVAL_FAST,
    CHECK_INTERVAL_SLOW,
    PAIRS_UPDATE_INTERVAL,
    API_RATE_LIMIT,
    TOP_VOLUME_LIMIT,
    API_MAX_CONCURRENT_REQUESTS,
    RISK_MULTIPLIER,
)

# 💾 DATABASE & BOT INTEGRATION
from database import save_signal, get_subscribers
from symbols_loader import get_top_symbols

# ⚙️ LOGGING SETUP
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scanner.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ARBITRAGE_SCANNER")
logger.info("🚀 Starting Arbitrage Scanner Pro")

# 🔄 RATE LIMITING SYSTEM
_last_request_time = 0
_min_interval = 1 / API_RATE_LIMIT if API_RATE_LIMIT > 0 else 0.2
semaphore = asyncio.Semaphore(API_MAX_CONCURRENT_REQUESTS if API_MAX_CONCURRENT_REQUESTS else 5)


# =======================
# 🔄 UTILITY FUNCTIONS
# =======================

async def rate_limit():
    """⏳ Гарантирует соблюдение лимита запросов к API"""
    global _last_request_time, _min_interval
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _min_interval:
        await asyncio.sleep(_min_interval - elapsed)
    _last_request_time = time.time()


def normalize_symbol(symbol: str, symbol_type: str) -> str:
    """🔄 Нормализует символы для сравнения"""
    symbol = symbol.upper()
    if symbol_type == 'spot':
        return symbol.replace("USDT", "").replace("USD", "")
    elif symbol_type == 'futures':
        base = re.sub(
            r"(_PERP|_USD|_USDT|_FUTURE|_THISWEEK|_NEXTWEEK|_QUARTER|_NEXTQUARTER)$",
            "",
            symbol
        )
        return base.replace("_", "")
    return symbol


def get_signal_strength(spread):
    """💪 Определяет силу сигнала на основе спреда"""
    if spread >= 8.0:
        return "🔥🔥🔥 ОЧЕНЬ СИЛЬНЫЙ"
    elif spread >= 5.0:
        return "🔥🔥 СИЛЬНЫЙ"
    elif spread >= 3.0:
        return "🔥 СРЕДНИЙ"
    else:
        return "⚠️ УМЕРЕННЫЙ"


def get_historical_context(spread):
    """📜 Предоставляет исторический контекст спреда"""
    if spread >= 15.0:
        return "📈 ИСТОРИЧЕСКИЙ МАКСИМУМ!"
    elif spread >= 10.0:
        return "🚀 НЕБЫВАЛЫЙ СПРЕД"
    elif spread >= 5.0:
        return "💎 ВЫСОКАЯ ВОЗМОЖНОСТЬ"
    else:
        return "📊 СТАНДАРТНАЯ АРБИТРАЖНАЯ СИТУАЦИЯ"


def get_risk_management(spread, volume):
    """⚖️ Рассчитывает рекомендации по управлению рисками"""
    leverage = min(int(spread * RISK_MULTIPLIER), 20)
    position_size = min(volume * 0.0001, 10000)
    return (
        f"• Кредитное плечо: {leverage}x\n"
        f"• Размер позиции: ${position_size:,.2f}\n"
        f"• Стоп-лосс: {max(1, spread / 2):.2f}% от точки входа"
    )


def get_liquidity_status(volume):
    """💧 Определяет уровень ликвидности"""
    if volume > 5000000:
        return "💧 ВЫСОКАЯ ЛИКВИДНОСТЬ"
    elif volume > 1000000:
        return "💧 СРЕДНЯЯ ЛИКВИДНОСТЬ"
    else:
        return "⚠️ НИЗКАЯ ЛИКВИДНОСТЬ"


def format_timestamp():
    """⏱ Форматирует временные метки в UTC и локальном времени"""
    utc_time = datetime.utcnow()
    local_time = utc_time.replace(tzinfo=pytz.utc).astimezone()
    return (
        f"UTC: {utc_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Локальное: {local_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )


def format_spot_url(symbol: str) -> str:
    """🔗 Форматирует URL спотовой страницы с UTM-метками"""
    return f"https://www.mexc.com/ru-RU/exchange/{symbol}?utm_source=arbitrage_bot"


def format_futures_url(symbol: str) -> str:
    """🔗 Форматирует URL фьючерсной страницы с UTM-метками"""
    return f"https://www.mexc.com/ru-RU/futures/{symbol}?utm_source=arbitrage_bot"


# =======================
# 📡 DATA FETCHING
# =======================

async def get_futures_symbols():
    """📊 Получает список доступных фьючерсных символов с защитой от ошибок"""
    url = "https://contract.mexc.com/api/v1/contract/detail"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                data = await resp.json()

                if not isinstance(data.get("data"), list):
                    logger.error("❌ Неверный формат данных фьючерсов")
                    return []

                symbols = []
                for item in data["data"]:
                    if not isinstance(item, dict):
                        continue
                    # Пробуем разные возможные ключи для символа
                    symbol = item.get("symbol") or item.get("contractName") or item.get("instrumentId")
                    if symbol:
                        symbols.append(symbol)

                logger.info(f"✅ Получено {len(symbols)} фьючерсных символов")
                return symbols

    except Exception as e:
        logger.error(f"❌ Ошибка при получении фьючерсных символов: {e}", exc_info=True)
        return []


async def get_top_symbol_pairs(limit=TOP_VOLUME_LIMIT):
    """🔍 Сопоставляет топ спотовые пары с фьючерсными с улучшенной обработкой"""
    futures_symbols_raw = await get_futures_symbols()
    if not futures_symbols_raw:
        logger.error("Не удалось получить фьючерсные символы")
        return []

    spot_symbols = [s for s in get_top_symbols(limit=limit * 3) if isinstance(s, str) and "TRUMP" not in s]
    futures_norm_map = {}

    for f_sym in futures_symbols_raw:
        if not isinstance(f_sym, str):
            continue
        norm_futures = normalize_symbol(f_sym, 'futures')
        futures_norm_map[norm_futures] = f_sym

    filtered = []
    for spot_sym in spot_symbols:
        norm_spot = normalize_symbol(spot_sym, 'spot')
        if norm_spot in futures_norm_map:
            filtered.append((spot_sym, futures_norm_map[norm_spot]))
            if len(filtered) >= limit:
                break

    logger.info(f"🔢 Отобрано {len(filtered)} пар для анализа")
    return filtered


async def fetch_spot_price(session, symbol, retries=3):
    """💹 Получает цену и объем спотовой пары"""
    async with semaphore:
        await rate_limit()
        url = f"https://api.mexc.com/api/v3/ticker/24hr?symbol={symbol}"
        for attempt in range(retries):
            try:
                async with session.get(url, timeout=10) as resp:
                    data = await resp.json()
                    return (
                        float(data.get("lastPrice") or data.get("price") or 0),
                        float(data.get("quoteVolume") or 0)
                    )
            except Exception as e:
                logger.error(f"Ошибка получения спотовой цены {symbol}, попытка {attempt + 1}: {e}", exc_info=True)
                await asyncio.sleep(1.5 * (attempt + 1))
        return 0, 0


async def fetch_futures_price(session, symbol, retries=3):
    """📈 Получает цену фьючерсного контракта"""
    async with semaphore:
        await rate_limit()
        url = f"https://contract.mexc.com/api/v1/contract/ticker?symbol={symbol}"

        for attempt in range(retries):
            try:
                async with session.get(url, timeout=10) as resp:
                    data = await resp.json()
                    if "data" in data and "lastPrice" in data["data"]:
                        return float(data["data"]["lastPrice"])

                    # Обработка лимита запросов
                    if data.get("code") == 510:
                        logger.warning(f"⚠️ Rate limit для {symbol}, попытка {attempt + 1}")
                        await asyncio.sleep(1.5 * (attempt + 1))
                    else:
                        logger.error(f"❌ Некорректные данные фьючерсов для {symbol}: {data}", exc_info=True)
            except Exception as e:
                logger.error(f"❌ Ошибка получения фьючерсной цены {symbol}, попытка {attempt + 1}: {e}", exc_info=True)
                await asyncio.sleep(1.5 * (attempt + 1))

        logger.error(f"🚨 Превышено число попыток для {symbol}")
        return 0


async def fetch_data_for_pair(session, spot_symbol, futures_symbol):
    """🔍 Собирает данные по паре и рассчитывает спред"""
    try:
        spot_price, volume = await fetch_spot_price(session, spot_symbol)
        futures_price = await fetch_futures_price(session, futures_symbol)

        # Пропускаем невалидные данные
        if spot_price <= 0 or futures_price <= 0:
            return None

        spread_percent = abs((futures_price - spot_price) / spot_price) * 100

        return {
            "spot_symbol": spot_symbol,
            "futures_symbol": futures_symbol,
            "spot_price": spot_price,
            "futures_price": futures_price,
            "spread_percent": spread_percent,
            "volume_spot": volume,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "bid_ask": (
                "Buy Spot / Sell Futures"
                if futures_price > spot_price
                else "Buy Futures / Sell Spot"
            )
        }
    except Exception as e:
        logger.error(f"❌ Ошибка обработки пары {spot_symbol}/{futures_symbol}: {e}", exc_info=True)
        return None


# =======================
# 💎 ПРОДВИНУТЫЕ СИГНАЛЫ
# =======================

def create_signal_message(signal: dict) -> str:
    """💎 Создает профессиональное сообщение о сигнале с аналитикой"""
    spread = signal['spread_percent']
    direction = "🔼 Фьючерс выше" if signal['futures_price'] > signal['spot_price'] else "🔽 Фьючерс ниже"

    # Аналитические метрики
    strength = get_signal_strength(spread)
    context = get_historical_context(spread)
    risk = get_risk_management(spread, signal['volume_spot'])
    liquidity = get_liquidity_status(signal['volume_spot'])

    # Эмодзи для визуализации спреда
    spread_emoji = "🔥" * min(int(spread), 5) + "💎" * (1 if spread > 5 else 0)

    # Форматирование чисел
    spot_price_fmt = f"{signal['spot_price']:.8f}".rstrip('0').rstrip('.')
    futures_price_fmt = f"{signal['futures_price']:.8f}".rstrip('0').rstrip('.')
    volume_fmt = f"${signal['volume_spot']:,.2f}"

    message = (
        "✨ *АРБИТРАЖНЫЙ СИГНАЛ* ✨\n\n"

        f"  📌 *{signal['spot_symbol']} / {signal['futures_symbol']}*\n"
        f"  {direction} на *{spread:.4f}%* {spread_emoji}\n"
        "├───────────────────────────────┤\n"
        f"│  💪 *Сила сигнала:* {strength}\n"
        f"│  🕰 *Контекст:* {context}\n"
        f"│  💧 *Ликвидность:* {liquidity}\n"
        f"│  💵 *Спот:* `{spot_price_fmt}`\n"
        f"│  📈 *Фьючерс:* `{futures_price_fmt}`\n"
        f"│  💰 *Объем (24ч):* `{volume_fmt}`\n"
        f"│  ⏱ *Время:*\n`{format_timestamp()}`\n"
        "├───────────────────────────────┤\n"
        f"│  ⚖️ *Стратегия:* {signal['bid_ask']}\n"
        f"│  ⚠️ *Управление рисками:*\n{risk}\n"
        "└───────────────────────────────┘\n\n"
        f"_Обнаружена арбитражная возможность с потенциалом доходности ~{spread * 0.8:.2f}% после комиссий_"
    )

    return message


# =======================
# 📨 NOTIFICATION SYSTEM
# =======================

async def notify_subscribers(signal: dict, send_message_func):
    """✉️ Рассылает стильные сообщения подписчикам с кнопками"""
    subscribers = get_subscribers()
    if not subscribers:
        logger.warning("Нет подписчиков для уведомления")
        return

    logger.info(f"👥 Рассылка сигнала {signal['spot_symbol']} для {len(subscribers)} подписчиков")
    sem_notify = asyncio.Semaphore(5)  # Ограничение на рассылку

    message_text = create_signal_message(signal)

    # Создаем клавиатуру с кнопками
    keyboard = [
        [
            InlineKeyboardButton("📊 Спот", url=format_spot_url(signal['spot_symbol'])),
            InlineKeyboardButton("📈 Фьючерс", url=format_futures_url(signal['futures_symbol']))
        ],
        [
            InlineKeyboardButton("📉 TradingView",
                                 url=f"https://www.tradingview.com/chart/?symbol=MEXC:{signal['spot_symbol']}"),
            InlineKeyboardButton("ℹ️ Помощь", callback_data="help")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    async def send_message(user_id):
        async with sem_notify:
            try:
                if send_message_func:
                    await send_message_func(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup
                    )
                    # Логируем успешную отправку
                    logger.debug(f"✅ Уведомление отправлено пользователю {user_id}")
                else:
                    logger.error("Функция отправки сообщений не определена!")
            except TimedOut:
                logger.warning(f"⏳ Timeout при отправке пользователю {user_id}")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")

    await asyncio.gather(*(send_message(uid) for uid in subscribers))


# =======================
# 🔄 PROCESSING CORE
# =======================

async def process_and_notify(session, pairs, send_message_func=None):
    """📡 Проверяет пары, сохраняет сигналы и уведомляет"""
    for spot_sym, fut_sym in pairs:
        signal = await fetch_data_for_pair(session, spot_sym, fut_sym)
        if not signal:
            continue

        spread = signal["spread_percent"]
        if spread >= THRESHOLD_PERCENT:
            save_signal(signal)  # Сохраняем в базу

            # Уведомляем при превышении порога уведомлений
            if spread >= THRESHOLD_NOTIFY_PERCENT:
                await notify_subscribers(signal, send_message_func)

            logger.info(f"📢 Сигнал {spot_sym}/{fut_sym}: Спред {spread:.4f}%")
        else:
            logger.debug(f"⏳ Спред {spread:.4f}% ниже порога для {spot_sym}/{fut_sym}")


# =======================
# 🔄 ОСНОВНОЙ ЦИКЛ
# =======================

async def main_loop(send_message_func=None):
    """🔄 Основной цикл сканирования"""
    logger.info("🚀 Запуск основного цикла")
    last_pairs_update = 0
    pairs = []

    async with aiohttp.ClientSession() as session:
        while True:
            now = time.time()

            # Обновляем список пар с топовым объемом
            if now - last_pairs_update > PAIRS_UPDATE_INTERVAL or not pairs:
                logger.info("🔄 Обновление списка торговых пар...")
                pairs = await get_top_symbol_pairs(limit=TOP_VOLUME_LIMIT)
                last_pairs_update = now
                logger.debug(f"📊 Активные пары: {pairs}")

            # Делим на быстрые и медленные для разного интервала
            fast_pairs = pairs[:50]
            slow_pairs = pairs[50:]

            if fast_pairs:
                try:
                    logger.info(f"⚡ Сканирование {len(fast_pairs)} быстрых пар")
                    await process_and_notify(session, fast_pairs, send_message_func)
                except Exception as e:
                    logger.error(f"❌ Ошибка сканирования быстрых пар: {e}", exc_info=True)

                await asyncio.sleep(CHECK_INTERVAL_FAST)

            if slow_pairs:
                try:
                    logger.info(f"🐢 Сканирование {len(slow_pairs)} медленных пар")
                    await process_and_notify(session, slow_pairs, send_message_func)
                except Exception as e:
                    logger.error(f"❌ Ошибка сканирования медленных пар: {e}", exc_info=True)

                await asyncio.sleep(CHECK_INTERVAL_SLOW)


# =======================
# 🎬 СТАРТ
# =======================

if __name__ == "__main__":
    try:
        # Проверка наличия необходимых библиотек
        try:
            import pytz
        except ImportError:
            logger.warning("Устанавливаем pytz для работы с часовыми поясами...")
            import subprocess

            subprocess.run(["pip", "install", "pytz"])
            import pytz

        # Запускаем без функции отправки сообщений
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("🛑 Прерывание пользователем")
    except Exception as e:
        logger.critical(f"🚨 Критическая ошибка: {e}", exc_info=True)