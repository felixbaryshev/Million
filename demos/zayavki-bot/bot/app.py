"""Точка входа. Вся логика диалога живёт в scenario.py."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Dict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    FSInputFile, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)

from .config import Config, ConfigError
from .scenario import Engine, Reply, Scenario, ScenarioError, Session
from .storage import Storage

log = logging.getLogger("bot")

#: Состояние диалогов живёт в памяти: при перезапуске незавершённые
#: диалоги теряются. Для потока в десятки заявок в день это
#: приемлемо; если клиенту важно иначе — переносим в БД.
sessions: Dict[int, Session] = {}


def keyboard(reply: Reply):
    if not reply.options:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=option)] for option in reply.options],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_dispatcher(engine: Engine, storage: Storage, config: Config) -> Dispatcher:
    dp = Dispatcher()

    def is_admin(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in config.admins

    async def notify_admins(bot: Bot, text: str) -> None:
        for admin_id in config.admins:
            try:
                await bot.send_message(admin_id, text)
            except Exception as exc:
                # Один недоступный админ не должен ронять приём заявок:
                # заявка уже сохранена, клиент ждёт ответа.
                log.warning("не доставлено админу %s: %s", admin_id, exc)

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        session = sessions.setdefault(message.chat.id, Session())
        for reply in engine.start(session):
            await message.answer(reply.text, reply_markup=keyboard(reply))

    @dp.message(Command("cancel"))
    async def on_cancel(message: Message) -> None:
        sessions.pop(message.chat.id, None)
        await message.answer(
            engine.scenario.cancelled, reply_markup=ReplyKeyboardRemove()
        )

    @dp.message(Command("stats"))
    async def on_stats(message: Message) -> None:
        if not is_admin(message):
            return
        from datetime import date
        today = date.today().isoformat()
        await message.answer(
            f"Всего заявок: {storage.count()}\n"
            f"Сегодня: {storage.count_since(today)}"
        )

    @dp.message(Command("leads"))
    async def on_leads(message: Message) -> None:
        if not is_admin(message):
            return
        leads = storage.recent(10)
        if not leads:
            await message.answer("Заявок пока нет.")
            return
        for lead in leads:
            await message.answer(lead.as_text())

    @dp.message(Command("export"))
    async def on_export(message: Message) -> None:
        if not is_admin(message):
            return
        if storage.count() == 0:
            await message.answer("Заявок пока нет — выгружать нечего.")
            return
        handle, path = tempfile.mkstemp(suffix=".csv", prefix="leads-")
        os.close(handle)
        try:
            rows = storage.export_csv(path)
            await message.answer_document(
                FSInputFile(path, filename="leads.csv"),
                caption=f"Выгрузка: {rows} заявок.",
            )
        finally:
            os.unlink(path)

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        session = sessions.get(message.chat.id)
        if session is None:
            await message.answer("Наберите /start, чтобы оставить заявку.")
            return

        reply = engine.answer(session, message.text)
        await message.answer(reply.text, reply_markup=keyboard(reply))

        if reply.finished and reply.lead:
            user = message.from_user
            lead = storage.add(
                user_id=user.id if user else message.chat.id,
                username=user.username if user else None,
                data=reply.lead,
            )
            await notify_admins(message.bot, lead.as_text())
            log.info("заявка %s сохранена", lead.id)

    @dp.message()
    async def on_other(message: Message) -> None:
        await message.answer(
            "Я понимаю только текст. Напишите ответ сообщением "
            "или наберите /start."
        )

    return dp


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config.from_env()
    scenario = Scenario.from_yaml(config.scenario_path)
    engine = Engine(scenario)
    storage = Storage(config.db_path)

    log.info(
        "сценарий: %s шагов, админов: %s, заявок в базе: %s",
        len(scenario.steps), len(config.admins), storage.count(),
    )

    bot = Bot(config.token, default=DefaultBotProperties(parse_mode=None))
    dp = build_dispatcher(engine, storage, config)
    await dp.start_polling(bot)


def main() -> int:
    try:
        asyncio.run(run())
    except (ConfigError, ScenarioError) as exc:
        print(f"\nНе запустился: {exc}\n")
        return 1
    except KeyboardInterrupt:
        print("\nОстановлен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
