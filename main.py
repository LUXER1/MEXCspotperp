#!/usr/bin/env python3
import asyncio
import sys
import logging
import signal
from contextlib import AsyncExitStack
from bot import Application, create_application  # Корректный импорт
from database import init_db, apply_migrations, cleanup_old_data, optimize_db
from scanner import main_loop
from config import DEBUG, TELEGRAM_TOKEN

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("arbitrage_bot.log")
    ]
)
logger = logging.getLogger(__name__)


async def send_message_wrapper(bot, chat_id, text):
    """Обертка для отправки сообщений через бота"""
    await bot.send_message(chat_id=chat_id, text=text)


async def start_monitoring(application):
    """Запуск мониторинга арбитражных возможностей"""
    await main_loop(
        send_message_func=lambda *args: send_message_wrapper(application.bot, *args)
    )


async def shutdown_handler(signal_name, tasks, application):
    """Обработчик завершения работы"""
    logger.info(f"Получен сигнал {signal_name}, остановка приложения...")

    # Отменяем все задачи
    for task in tasks:
        if task and not task.done():
            task.cancel()

    # Останавливаем приложение
    if application:
        await application.stop()


async def main():
    application = None
    tasks = []

    async with AsyncExitStack() as stack:
        try:
            logger.info("🛢 Инициализация базы данных...")
            await asyncio.to_thread(init_db)
            await asyncio.to_thread(apply_migrations)
            await asyncio.to_thread(cleanup_old_data)
            await asyncio.to_thread(optimize_db)

            logger.info("🤖 Инициализация Telegram бота...")
            application = await create_application("8070188488:AAGuc77t-x5s7YEsAY7ZejnuFO4HxU0kVcE")  # Тестовый токен  # <- передаём токен
            await application.initialize()
            await application.start()

            logger.info("🔍 Запуск мониторинга арбитражных возможностей...")
            monitoring_task = asyncio.create_task(start_monitoring(application))
            polling_task = asyncio.create_task(application.updater.start_polling())

            tasks = [monitoring_task, polling_task]

            # Регистрируем обработчики сигналов
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig,
                    lambda: asyncio.create_task(
                        shutdown_handler(sig.name, tasks, application)
                    )
                )

            await asyncio.gather(*tasks)

        except asyncio.CancelledError:
            logger.info("Получен запрос на остановку...")
        except Exception as e:
            logger.exception(f"Критическая ошибка: {e}")
            raise
        finally:
            logger.info("👋 Работа завершена")
            if application:
                await application.stop()


def handle_sync_exceptions():
    """Обработчик синхронных исключений"""
    logger.error("Необработанное синхронное исключение", exc_info=True)
    sys.exit(1)


if __name__ == "__main__":
    sys.excepthook = lambda *args: handle_sync_exceptions()

    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nПриложение остановлено пользователем")
        sys.exit(0)