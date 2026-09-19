"""Проверка и нормализация ответов пользователя.

Вынесено отдельно от телеграма: это чистые функции, их можно
тестировать и переиспользовать в любом другом проекте.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

_NON_DIGIT = re.compile(r"\D")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def normalize_phone(raw: str) -> Optional[str]:
    """Привести телефон к виду +7XXXXXXXXXX.

    Принимает всё, что реально пишут люди: 8 916 123-45-67,
    +7 (916) 123 45 67, 9161234567. Иностранные номера принимаются,
    если введены с плюсом.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None

    international = raw.startswith("+")
    digits = _NON_DIGIT.sub("", raw)

    if not digits:
        return None

    if international and not digits.startswith("7"):
        # Иностранный номер: не трогаем, только проверяем длину.
        return f"+{digits}" if 8 <= len(digits) <= 15 else None

    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = digits[1:]
    elif len(digits) != 10:
        return None

    if digits[0] != "9":
        # Российские мобильные начинаются с 9. Городские без кода
        # оставляем как есть, но и не выдаём за мобильный.
        return None

    return "+7" + digits


def validate_email(raw: str) -> Optional[str]:
    """Проверить почту. Намеренно мягкая проверка."""
    if not raw:
        return None
    value = raw.strip().lower()
    # Строгая проверка почты по RFC отвергает валидные адреса и
    # раздражает клиентов. Здесь достаточно поймать опечатку.
    return value if _EMAIL.match(value) else None


def parse_number(raw: str) -> Optional[float]:
    """Разобрать число: '1 500', '1500,50', '1500.5'."""
    if not raw:
        return None
    cleaned = raw.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def match_choice(raw: str, options: List[str]) -> Optional[str]:
    """Сопоставить ответ со списком вариантов.

    Принимает и сам вариант, и его номер — люди часто отвечают цифрой,
    даже когда нажать можно кнопку.
    """
    if not raw or not options:
        return None
    value = raw.strip()

    for option in options:
        if value.lower() == option.lower():
            return option

    if value.isdigit():
        index = int(value) - 1
        if 0 <= index < len(options):
            return options[index]

    return None


def looks_like_junk(raw: str) -> bool:
    """Отсечь явный мусор в текстовом поле.

    Не строгость ради строгости: пустая заявка из одного символа
    тратит время владельца бизнеса, который её открывает.
    """
    value = (raw or "").strip()
    if len(value) < 2:
        return True
    if not re.search(r"[A-Za-zА-Яа-яЁё0-9]", value):
        return True
    return False
