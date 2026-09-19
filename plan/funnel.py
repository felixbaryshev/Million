#!/usr/bin/env python3
"""Калькулятор воронки: что даёт бюджет при разных конверсиях.

Нужен для одного решения: докладывать бюджет или менять предложение.
Средние цифры по всей рекламе это решение скрывают, поэтому считать
надо по каждой связке отдельно.

    python funnel.py                      # базовый расчёт
    python funnel.py --budget 250000      # свой бюджет
    python funnel.py --table              # таблица сценариев
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


def money(value: float, width: int = 0) -> str:
    """Число с пробелами между разрядами, как принято в русском тексте."""
    text = f"{value:,.0f}".replace(",", "\u00a0")
    return text.rjust(width) if width else text


@dataclass
class Funnel:
    budget: float
    cost_per_lead: float
    lead_to_consult: float
    consult_to_sale: float
    avg_check: float

    @property
    def leads(self) -> float:
        return self.budget / self.cost_per_lead if self.cost_per_lead else 0.0

    @property
    def consults(self) -> float:
        return self.leads * self.lead_to_consult

    @property
    def clients(self) -> float:
        return self.consults * self.consult_to_sale

    @property
    def revenue(self) -> float:
        return self.clients * self.avg_check

    @property
    def cac(self) -> float:
        """Во сколько обходится один клиент."""
        return self.budget / self.clients if self.clients else float("inf")

    @property
    def profit(self) -> float:
        return self.revenue - self.budget

    @property
    def roi(self) -> float:
        return self.revenue / self.budget if self.budget else 0.0

    def sessions(self, per_program: int = 10) -> float:
        """Сколько сессий придётся провести. Про ёмкость расписания."""
        return self.clients * per_program

    def verdict(self) -> str:
        if self.clients < 1:
            return "Связка не даёт даже одного клиента — выключать."
        if self.cac >= self.avg_check:
            return "Клиент дороже, чем платит. Убыточно при любом масштабе."
        if self.roi < 2:
            return "Окупается, но слабо. Масштабировать рано."
        return "Работает. Можно увеличивать бюджет."

    def report(self) -> str:
        sessions = self.sessions()
        lines = [
            f"Бюджет               {money(self.budget, 12)} ₽",
            f"Цена заявки          {money(self.cost_per_lead, 12)} ₽",
            f"Заявок               {money(self.leads, 12)}",
            f"Консультаций         {money(self.consults, 12)}  "
            f"({self.lead_to_consult:.0%} от заявок)",
            f"Клиентов             {self.clients:>12.1f}  "
            f"({self.consult_to_sale:.0%} от консультаций)",
            "",
            f"Средний чек          {money(self.avg_check, 12)} ₽",
            f"Выручка              {money(self.revenue, 12)} ₽",
            f"Прибыль              {money(self.profit, 12)} ₽",
            f"Цена клиента         {money(self.cac, 12)} ₽",
            f"ROI                  {self.roi:>12.1f}x",
            "",
            f"Сессий провести      {money(sessions, 12)}  "
            f"(~{sessions / 22:.1f} в день при 22 рабочих днях)",
            "",
            self.verdict(),
        ]
        return "\n".join(lines)


SCENARIOS = [
    ("Первый месяц, всё сырое", 3500, 0.30, 0.15),
    ("Реалистичный", 3000, 0.35, 0.18),
    ("Отлаженная воронка", 2000, 0.40, 0.25),
    ("Очень хорошо", 1500, 0.45, 0.30),
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--budget", type=float, default=250_000)
    p.add_argument("--cpl", type=float, default=3000, help="цена заявки")
    p.add_argument("--to-consult", type=float, default=0.35)
    p.add_argument("--to-sale", type=float, default=0.18)
    p.add_argument("--check", type=float, default=80_000, help="средний чек")
    p.add_argument("--table", action="store_true", help="сравнить сценарии")
    args = p.parse_args()

    if args.table:
        header = f"{'Сценарий':<26}{'Клиентов':>10}{'Выручка':>14}{'Прибыль':>14}{'ROI':>7}"
        print(header)
        print("-" * len(header))
        for name, cpl, consult, sale in SCENARIOS:
            f = Funnel(args.budget, cpl, consult, sale, args.check)
            print(f"{name:<26}{f.clients:>10.1f}"
                  f"{money(f.revenue, 14)}{money(f.profit, 14)}{f.roi:>7.1f}x")
        print(f"\nБюджет {money(args.budget)} ₽, чек {money(args.check)} ₽")
        return 0

    print(Funnel(args.budget, args.cpl, args.to_consult, args.to_sale,
                 args.check).report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
