import sqlite3
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from config import TELEGRAM_TOKEN, TELEGRAM_GROUP_ID, THREAD_ID
from database import (
    add_subscriber, remove_subscriber, get_subscribers,
    get_user_settings, update_user_settings
)

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Состояния для диалога
SET_SPREAD, SET_VOLUME = range(2)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Арбитражный бот для MEXC\n"
        "Автоматически отслеживает спреды между спотом и фьючерсами\n\n"
        "Доступные команды:\n"
        "/status - Статус бота\n"
        "/stats - Статистика сигналов\n"
        "/subscribe - Подписаться на крупные сигналы\n"
        "/unsubscribe - Отписаться от рассылки\n"
        "/settings - Настройки\n"
        "/help - Помощь"
    )

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Справка по боту:\n\n"
        "Этот бот отслеживает арбитражные возможности между спотовым и фьючерсным рынками на бирже MEXC.\n"
        "Используйте /subscribe для получения уведомлений о крупных спредах."
    )

# /status
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot_id = context.bot.id
        chat_member = await context.bot.get_chat_member(
            chat_id=TELEGRAM_GROUP_ID,
            user_id=bot_id
        )
        status = chat_member.status
        await update.message.reply_text(f"✅ Бот в группе: {status}")
    except Exception as e:
        logging.error(f"Ошибка проверки статуса: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}\nБот не в группе!")

# /stats
async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = sqlite3.connect("arbitrage.db")
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM arbitrage_signals")
        total_signals = c.fetchone()[0]

        c.execute("SELECT symbol, spread_percent, timestamp FROM arbitrage_signals ORDER BY id DESC LIMIT 5")
        last_signals = c.fetchall()

        c.execute("SELECT symbol, MAX(spread_percent) FROM arbitrage_signals")
        best_signal = c.fetchone()

        conn.close()

        message = f"📊 Статистика сигналов:\n\n"
        message += f"Всего сигналов: {total_signals}\n"
        if best_signal and best_signal[0] is not None:
            message += f"Лучший сигнал: {best_signal[0]} ({best_signal[1]:.4f}%)\n\n"
        else:
            message += "Лучший сигнал: отсутствует\n\n"

        message += "Последние 5 сигналов:\n"
        for symbol, spread, timestamp in last_signals:
            message += f"- {symbol}: {spread:.4f}% ({timestamp})\n"

        await update.message.reply_text(message)
    except Exception as e:
        logging.error(f"Ошибка получения статистики: {e}")
        await update.message.reply_text(f"Ошибка получения статистики: {e}")

# /subscribe
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    added = add_subscriber(user_id)
    if added:
        await update.message.reply_text("✅ Вы подписались на уведомления о крупных спредах.")
    else:
        await update.message.reply_text("🔔 Вы уже подписаны.")

# /unsubscribe
async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    remove_subscriber(user_id)
    await update.message.reply_text("🚫 Вы отписались от уведомлений.")

# /thread
async def get_thread_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📌 Текущая ветка для сигналов:\n\n"
        f"ID группы: `{TELEGRAM_GROUP_ID}`\n"
        f"ID ветки: `{THREAD_ID}`",
        parse_mode="Markdown"
    )

# /settings
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    min_spread = settings.get("min_spread", 1.0)
    min_volume = settings.get("min_volume", 100000)

    keyboard = [
        [InlineKeyboardButton("🔧 Изменить спред", callback_data="set_spread")],
        [InlineKeyboardButton("💸 Изменить объем", callback_data="set_volume")],
        [InlineKeyboardButton("↩️ Назад", callback_data="cancel")]
    ]

    message = (
        f"⚙️ Настройки пользователя:\n\n"
        f"📊 Минимальный спред: {min_spread:.2f}%\n"
        f"💰 Минимальный объем: {min_volume:,.0f} USDT"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

    return ConversationHandler.END

# Задание нового спреда
async def ask_spread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите новый минимальный спред в процентах (например: 1.5):")
    return SET_SPREAD

async def set_spread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text.replace(",", "."))
        update_user_settings(update.effective_user.id, "min_spread", value)
        await update.message.reply_text(f"✅ Минимальный спред обновлён: {value:.2f}%")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите число, например 1.5:")
        return SET_SPREAD
    return await show_settings(update, context)

# Задание нового объема
async def ask_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите минимальный объем в USDT (например: 100000):")
    return SET_VOLUME

async def set_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text.replace(",", ""))
        update_user_settings(update.effective_user.id, "min_volume", value)
        await update.message.reply_text(f"✅ Минимальный объем обновлён: {value:,.0f} USDT")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите число, например 100000:")
        return SET_VOLUME
    return await show_settings(update, context)

# Отмена
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❎ Настройки отменены.")
    return ConversationHandler.END

# Регистрация всех хендлеров
application = Application.builder().token(TELEGRAM_TOKEN).build()

settings_conv = ConversationHandler(
    entry_points=[CommandHandler("settings", show_settings)],
    states={
        SET_SPREAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_spread)],
        SET_VOLUME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_volume)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    allow_reentry=True
)

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("status", check_status))
application.add_handler(CommandHandler("stats", get_stats))
application.add_handler(CommandHandler("subscribe", subscribe))
application.add_handler(CommandHandler("unsubscribe", unsubscribe))
application.add_handler(CommandHandler("thread", get_thread_info))
application.add_handler(settings_conv)
application.add_handler(CallbackQueryHandler(ask_spread, pattern="^set_spread$"))
application.add_handler(CallbackQueryHandler(ask_volume, pattern="^set_volume$"))
application.add_handler(CallbackQueryHandler(show_settings, pattern="^cancel$"))
