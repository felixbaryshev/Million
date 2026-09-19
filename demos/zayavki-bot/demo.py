#!/usr/bin/env python3
"""Прогон сценария в терминале — без телеграма и без токена.

Нужен для двух вещей: показать заказчику, как будет выглядеть диалог,
до того как он что-то оплатил; и проверить новый сценарий за десять
секунд, не поднимая бота.

    python demo.py [scenario.yaml]
"""

import sys

from bot.scenario import Engine, Scenario, ScenarioError, Session


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "scenario.yaml"

    try:
        scenario = Scenario.from_yaml(path)
    except ScenarioError as exc:
        print(f"Сценарий не загрузился: {exc}")
        return 1

    engine = Engine(scenario)
    session = Session()

    print("=" * 60)
    print(f"Демо диалога: {path} ({len(scenario.steps)} шагов)")
    print("Ctrl+C — выход, «назад» — вернуться на шаг")
    print("=" * 60)

    for reply in engine.start(session):
        print(f"\nБОТ: {reply.text}")
        if reply.options:
            print("     " + " | ".join(f"[{o}]" for o in reply.options))

    try:
        while not session.done:
            answer = input("\nВЫ:  ").strip()
            reply = engine.answer(session, answer)
            print(f"\nБОТ: {reply.text}")
            if reply.options:
                print("     " + " | ".join(f"[{o}]" for o in reply.options))
            if reply.progress and not reply.finished:
                print(f"     ({reply.progress})")
    except (KeyboardInterrupt, EOFError):
        print("\n\nПрервано.")
        return 0

    print("\n" + "=" * 60)
    print("Заявка, которая уйдёт владельцу:\n")
    for key, value in (reply.lead or {}).items():
        print(f"  {key}: {value}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
