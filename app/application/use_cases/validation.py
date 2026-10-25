from __future__ import annotations

import re
from typing import Optional

NON_DIGIT_RE = re.compile(r"\D+")
WHITESPACE_RE = re.compile(r"\s+")


def normalize_phone_ru(raw: str) -> Optional[str]:
    digits = NON_DIGIT_RE.sub("", raw)

    if len(digits) == 11 and digits[0] in {"7", "8"}:
        digits = "7" + digits[1:]
        return f"+{digits}"

    if len(digits) == 10 and digits[0] == "9":
        return f"+7{digits}"

    return None


def validate_full_name(raw: str) -> Optional[str]:
    name = WHITESPACE_RE.sub(" ", raw.strip())
    if 2 <= len(name) <= 60:
        return name
    return None
