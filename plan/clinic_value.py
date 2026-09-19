#!/usr/bin/env python3
"""Сколько клиника теряет на страхе пациентов.

Инструмент продажи, а не аналитики. На встрече цифры заполняются
данными самой клиники — тогда вывод делает не продавец, а
собеседник, и спорить ему не с чем.

Значения по умолчанию намеренно заниженные. Завышенная оценка
разрушает разговор в первую минуту: коммерческий директор знает свою
клинику лучше вас.

    python clinic_value.py --patients 400 --check 45000
    python clinic_value.py --patients 400 --check 45000 --program 30000
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


def money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


@dataclass
class Clinic:
    patients_per_month: int
    avg_check: float
    #: Доля первичных обращений, где страх мешает согласиться на
    #: полноценный план лечения. Консервативная оценка; на встрече
    #: заменяется наблюдением самой клиники.
    fear_share: float = 0.10
    #: Какая часть из них отказывается или бесконечно откладывает.
    refuse_share: float = 0.50
    #: Сколько таких пациентов реально возвращается к лечению после
    #: работы со страхом. Тоже консервативно.
    recovery_rate: float = 0.50

    @property
    def afraid(self) -> float:
        return self.patients_per_month * self.fear_share

    @property
    def lost_patients(self) -> float:
        return self.afraid * self.refuse_share

    @property
    def lost_monthly(self) -> float:
        return self.lost_patients * self.avg_check

    @property
    def lost_yearly(self) -> float:
        return self.lost_monthly * 12

    def recovered_monthly(self) -> float:
        return self.lost_patients * self.recovery_rate * self.avg_check

    def report(self, program_price: float) -> str:
        recovered = self.recovered_monthly()
        patients_helped = self.lost_patients * self.recovery_rate
        cost = patients_helped * program_price
        net = recovered - cost
        roi = recovered / cost if cost else 0.0

        lines = [
            "Что происходит сейчас",
            f"  Первичных пациентов в месяц      {self.patients_per_month:>10}",
            f"  Из них страх мешает лечению      {self.afraid:>10.0f}  "
            f"({self.fear_share:.0%})",
            f"  Отказываются или откладывают     {self.lost_patients:>10.0f}  "
            f"({self.refuse_share:.0%} от них)",
            f"  Средний чек плана лечения        {money(self.avg_check):>10} ₽",
            "",
            f"  Упущено в месяц                  {money(self.lost_monthly):>10} ₽",
            f"  Упущено за год                   {money(self.lost_yearly):>10} ₽",
            "",
            "Что меняется",
            f"  Возвращаются к лечению           {patients_helped:>10.0f}  "
            f"({self.recovery_rate:.0%} из отказавшихся)",
            f"  Выручка клиники в месяц          {money(recovered):>10} ₽",
            f"  Стоимость работы                 {money(cost):>10} ₽",
            f"  Чистыми клинике                  {money(net):>10} ₽",
            f"  На вложенный рубль               {roi:>10.1f} ₽",
            "",
            f"  За год чистыми                   {money(net * 12):>10} ₽",
        ]
        return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--patients", type=int, required=True,
                   help="первичных пациентов в месяц")
    p.add_argument("--check", type=float, required=True,
                   help="средний чек плана лечения")
    p.add_argument("--program", type=float, default=30_000,
                   help="цена вашей программы на одного пациента")
    p.add_argument("--fear", type=float, default=0.10,
                   help="доля пациентов, которым страх мешает")
    p.add_argument("--refuse", type=float, default=0.50,
                   help="какая часть из них отказывается")
    p.add_argument("--recovery", type=float, default=0.50,
                   help="какая часть возвращается после работы со страхом")
    args = p.parse_args()

    clinic = Clinic(args.patients, args.check, args.fear, args.refuse, args.recovery)
    print(clinic.report(args.program))
    print()
    print("Доли — оценка. На встрече заменяются цифрами клиники:")
    print("спросите, сколько планов лечения срывается из-за страха.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
