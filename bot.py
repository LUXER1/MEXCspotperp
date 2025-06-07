#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ========================================================
# 🤖 ARBITRAGE NOTIFICATION BOT FOR MEXC EXCHANGE
# ========================================================

import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_TOKEN, TELEGRAM_GROUP_ID
from database import add_subscriber, remove_subscriber, get_subscribers

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ARBITRAGE_BOT")
logger.info("🤖 Starting Arbitrage Notification Bot")

# Константы и состояние пользователя
THRESHOLD_NOTIFY_PERCENT = 0.7
MAIN_MENU = "main_menu"
SETTINGS_MENU = "settings_menu"
user_settings = {}


def create_main_menu():
    """Главное меню с кнопками."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус системы", callback_data="status")],
        [InlineKeyboardButton("📈 Статистика сигналов", callback_data="stats")],
        [
            InlineKeyboardButton("✅ Подписаться", callback_data="subscribe"),
            InlineKeyboardButton("❌ Отписаться", callback_data="unsubscribe"),
        ],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ])


def create_settings_menu():
    """Меню настроек пользователя."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📏 Изменить спред", callback_data="set_spread"),
            InlineKeyboardButton("💵 Изменить объем", callback_data="set_volume"),
        ],
        [
            InlineKeyboardButton("🔗 Вкл/Выкл ссылки", callback_data="toggle_links"),
            InlineKeyboardButton("🔔 Вкл/Выкл уведомления", callback_data="toggle_notifications"),
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")],
    ])


async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start — приветствие и главное меню."""
    user = update.effective_user
    welcome_message = (
        f"👋 Привет, {user.first_name}!\n\n"
        "🤖 Я - *Арбитражный Бот для MEXC*\n"
        "📊 Моя задача - отслеживать выгодные спреды между спотовым и фьючерсным рынками.\n\n"
        "🔔 Подпишитесь на уведомления, чтобы получать сигналы о крупных арбитражных возможностях!"
    )
    await update.message.reply_text(
        welcome_message,
        parse_mode="Markdown",
        reply_markup=create_main_menu()
    )
    context.user_data["menu"] = MAIN_MENU
    logger.info(f"👤 Новый пользователь: {user.id} - {user.full_name}")


async def get_help_text():
    """Текст помощи для команды /help."""
    return (
        "ℹ️ *Справка по боту*\n\n"
        "🔹 Этот бот отслеживает арбитражные возможности между спотовым и фьючерсным рынками на бирже MEXC.\n\n"
        "🔸 *Основные команды:*\n"
        "▫️ /start - Запуск бота и главное меню\n"
        "▫️ /help - Показать эту справку\n\n"
        "🔸 *Функционал:*\n"
        "- Подписка на уведомления\n"
        "- Настройка параметров сигналов\n"
        "- Просмотр статистики\n"
        "- Управление отображением ссылок\n\n"
        "⚡ Используйте меню для навигации!"
    )


async def check_bot_status(context):
    """Проверка статуса бота в группе."""
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=TELEGRAM_GROUP_ID,
            user_id=context.bot.id
        )
        if chat_member.status in ["administrator", "member"]:
            return "🟢 *Статус бота:* Активен и работает корректно"
        return "🟡 *Статус бота:* Бот не активен в группе"
    except Exception as e:
        logger.error(f"❌ Ошибка проверки статуса бота: {e}")
        return "🔴 *Статус бота:* Ошибка подключения"


async def get_signal_stats():
    """Получение статистики сигналов из базы."""
    try:
        conn = sqlite3.connect("arbitrage.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM arbitrage_signals")
        total_signals = c.fetchone()[0]

        c.execute("SELECT AVG(spread_percent) FROM arbitrage_signals")
        avg_spread = c.fetchone()[0] or 0

        c.execute("""
            SELECT symbol, spread_percent, timestamp 
            FROM arbitrage_signals 
            ORDER BY id DESC 
            LIMIT 5
        """)
        last_signals = c.fetchall()

        c.execute("""
            SELECT symbol, MAX(spread_percent), timestamp 
            FROM arbitrage_signals
        """)
        best_signal = c.fetchone()

        conn.close()

        message = "📊 *Статистика сигналов:*\n\n"
        message += f"• Всего сигналов: `{total_signals:,}`\n"
        message += f"• Средний спред: `{avg_spread:.4f}%`\n\n"

        if best_signal and best_signal[0]:
            message += (
                f"🏆 *Лучший сигнал:*\n"
                f"▫️ Пара: `{best_signal[0]}`\n"
                f"▫️ Спред: `{best_signal[1]:.4f}%`\n"
                f"▫️ Время: `{best_signal[2]}`\n\n"
            )

        if last_signals:
            message += "⏱ *Последние 5 сигналов:*\n"
            for sym, sp, ts in last_signals:
                message += f"- `{sym}`: {sp:.4f}% ({ts.split()[1]})\n"

        return message
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        return "⚠️ Не удалось получить статистику. Попробуйте позже."


async def get_settings_text(settings):
    """Формирует текст для меню настроек."""
    return (
        "⚙️ *Настройки пользователя:*\n\n"
        f"• Минимальный спред: `{settings.get('min_spread', THRESHOLD_NOTIFY_PERCENT) * 100:.2f}%`\n"
        f"• Минимальный объем: `{settings.get('min_volume', 0)}`\n"
        f"• Ссылки: `{'Включены' if settings.get('links_enabled', True) else 'Выключены'}`\n"
        f"• Уведомления: `{'Включены' if settings.get('notifications', False) else 'Выключены'}`\n\n"
        "Выберите параметр для изменения:"
    )


async def show_settings_menu(query, settings):
    """Показать меню настроек с текущими параметрами."""
    text = await get_settings_text(settings)
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=create_settings_menu()
    )


async def handle_menu_interaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки меню."""
    query = update.callback_query
    user = query.from_user
    await query.answer()

    # Получаем или создаем настройки пользователя
    settings = user_settings.setdefault(user.id, {
        "min_spread": THRESHOLD_NOTIFY_PERCENT,
        "min_volume": 0,
        "links_enabled": True,
        "notifications": user.id in get_subscribers(),
    })

    # Обработка основных действий меню
    if query.data == "status":
        status = await check_bot_status(context)
        await query.edit_message_text(
            status,
            parse_mode="Markdown",
            reply_markup=create_main_menu()
        )
        context.user_data["menu"] = MAIN_MENU

    elif query.data == "stats":
        stats = await get_signal_stats()
        await query.edit_message_text(
            stats,
            parse_mode="Markdown",
            reply_markup=create_main_menu()
        )
        context.user_data["menu"] = MAIN_MENU

    elif query.data == "subscribe":
        if add_subscriber(user.id):
            settings["notifications"] = True
            response = "✅ Вы успешно подписались на уведомления!"
        else:
            response = "ℹ️ Вы уже подписаны на уведомления."
        await query.edit_message_text(response, reply_markup=create_main_menu())

    elif query.data == "unsubscribe":
        if remove_subscriber(user.id):
            settings["notifications"] = False
            response = "🔕 Вы отписались от уведомлений."
        else:
            response = "ℹ️ Вы не были подписаны."
        await query.edit_message_text(response, reply_markup=create_main_menu())

    elif query.data == "settings":
        await show_settings_menu(query, settings)
        context.user_data["menu"] = SETTINGS_MENU

    elif query.data == "help":
        help_text = await get_help_text()
        await query.edit_message_text(
            help_text,
            parse_mode="Markdown",
            reply_markup=create_main_menu()
        )

    elif query.data == "back_to_main":
        await query.edit_message_text(
            "📱 *Главное меню:*",
            parse_mode="Markdown",
            reply_markup=create_main_menu()
        )
        context.user_data["menu"] = MAIN_MENU

    # Обработка действий в меню настроек
    elif context.user_data.get("menu") == SETTINGS_MENU:
        if query.data == "toggle_links":
            settings["links_enabled"] = not settings["links_enabled"]
            await show_settings_menu(query, settings)

        elif query.data == "toggle_notifications":
            if settings["notifications"]:
                if remove_subscriber(user.id):
                    settings["notifications"] = False
                    response = "🔕 Уведомления отключены."
                else:
                    response = "⚠️ Не удалось отключить уведомления."
            else:
                if add_subscriber(user.id):
                    settings["notifications"] = True
                    response = "🔔 Уведомления включены."
                else:
                    response = "⚠️ Не удалось включить уведомления."

            # Обновляем сообщение с новым статусом
            await query.edit_message_text(
                response + "\n\n" + await get_settings_text(settings),
                parse_mode="Markdown",
                reply_markup=create_settings_menu()
            )

        elif query.data == "set_spread":
            await query.edit_message_text(
                "Введите минимальный спред в процентах (например, 0.7):"
            )
            context.user_data["awaiting_spread"] = True

        elif query.data == "set_volume":
            await query.edit_message_text(
                "Введите минимальный объем для сигналов:"
            )
            context.user_data["awaiting_volume"] = True

    else:
        await query.answer("Команда не распознана.", show_alert=True)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода текста для настройки параметров."""
    user = update.effective_user
    text = update.message.text.strip()
    settings = user_settings.setdefault(user.id, {
        "min_spread": THRESHOLD_NOTIFY_PERCENT,
        "min_volume": 0,
        "links_enabled": True,
        "notifications": user.id in get_subscribers(),
    })

    if context.user_data.get("awaiting_spread"):
        try:
            val = float(text.replace(",", "."))
            if val <= 0:
                raise ValueError("Спред должен быть положительным числом.")
            settings["min_spread"] = val / 100
            await update.message.reply_text(
                f"✅ Минимальный спред установлен: {val:.2f}%"
            )
            context.user_data["awaiting_spread"] = False
            await update.message.reply_text(
                await get_settings_text(settings),
                parse_mode="Markdown",
                reply_markup=create_settings_menu()
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Некорректный ввод. Введите число, например: 0.7"
            )

    elif context.user_data.get("awaiting_volume"):
        try:
            val = float(text.replace(",", "."))
            if val < 0:
                raise ValueError("Объем не может быть отрицательным.")
            settings["min_volume"] = val
            await update.message.reply_text(
                f"✅ Минимальный объем установлен: {val}"
            )
            context.user_data["awaiting_volume"] = False
            await update.message.reply_text(
                await get_settings_text(settings),
                parse_mode="Markdown",
                reply_markup=create_settings_menu()
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Некорректный ввод. Введите положительное число."
            )

    else:
        await update.message.reply_text(
            "ℹ️ Используйте меню для взаимодействия с ботом.\n"
            "Для помощи введите /help"
        )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка неизвестных команд."""
    await update.message.reply_text(
        "❓ Неизвестная команда.\nВведите /help для получения списка команд."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /help."""
    help_text = await get_help_text()
    await update.message.reply_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=create_main_menu()
    )


def create_application(token):  # Добавляем параметр
    application = Application.builder().token(token).build()



    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start_bot))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_menu_interaction))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    return application

def main():
    """Основная функция запуска бота."""
    try:
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", start_bot))
        application.add_handler(CommandHandler("help", help_command))

        # Добавляем обработчики callback и текстовых сообщений
        application.add_handler(CallbackQueryHandler(handle_menu_interaction))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

        logger.info("🚀 Bot started polling...")
        application.run_polling()

    except Exception as e:
        logger.error(f"❌ Critical error: {e}")
        raise


if __name__ == "__main__":
    main()