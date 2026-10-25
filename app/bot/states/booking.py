from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    idle = State()
    choosing_service = State()
    choosing_date = State()
    choosing_slot = State()
    reschedule_choosing_date = State()
    reschedule_choosing_slot = State()
    input_name = State()
    input_phone = State()
    confirming = State()
    done = State()
