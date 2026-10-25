from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import start_router
from app.infrastructure.config import get_settings
from app.infrastructure.logging import configure_logging

logger = logging.getLogger(__name__)


async def _run_polling() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or settings.telegram_bot_token == "replace_me":
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start_router)

    logger.info("Starting bot polling")
    await dp.start_polling(bot, polling_timeout=settings.bot_polling_timeout)


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(_run_polling())


if __name__ == "__main__":
    run()
