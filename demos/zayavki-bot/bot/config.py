"""Настройки из переменных окружения.

Проверяются при старте. Бот, которому не хватает токена, должен
падать сразу с понятным сообщением, а не через час молчания.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    token: str
    admins: List[int] = field(default_factory=list)
    scenario_path: str = "scenario.yaml"
    db_path: str = "leads.db"

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError(
                "Не задан BOT_TOKEN.\n"
                "Получите токен у @BotFather и запустите так:\n"
                "  BOT_TOKEN=123:ABC ADMIN_IDS=123456 python -m bot.app"
            )

        raw_admins = os.getenv("ADMIN_IDS", "").strip()
        admins: List[int] = []
        for chunk in raw_admins.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if not chunk.lstrip("-").isdigit():
                raise ConfigError(
                    f"ADMIN_IDS: '{chunk}' не похоже на числовой id. "
                    "Свой id можно узнать у @userinfobot."
                )
            admins.append(int(chunk))

        if not admins:
            raise ConfigError(
                "Не задан ADMIN_IDS — некому получать заявки.\n"
                "Узнайте свой id у @userinfobot и укажите ADMIN_IDS=<id>."
            )

        return cls(
            token=token,
            admins=admins,
            scenario_path=os.getenv("SCENARIO_PATH", "scenario.yaml"),
            db_path=os.getenv("DB_PATH", "leads.db"),
        )
