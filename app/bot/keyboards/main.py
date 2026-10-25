from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.localization import LOCALE_EN, LOCALE_RU, menu_label, normalize_locale


def get_main_menu(locale: str = LOCALE_RU) -> ReplyKeyboardMarkup:
    lang = normalize_locale(locale)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=menu_label(lang, "book"))],
            [KeyboardButton(text=menu_label(lang, "quick"))],
            [
                KeyboardButton(text=menu_label(lang, "my_bookings")),
                KeyboardButton(text=menu_label(lang, "cancel")),
            ],
            [KeyboardButton(text=menu_label(lang, "language"))],
        ],
        resize_keyboard=True,
    )


def get_language_picker_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data=f"lang:{LOCALE_RU}")
    builder.button(text="🇬🇧 English", callback_data=f"lang:{LOCALE_EN}")
    builder.adjust(2)
    return builder.as_markup()
