"""Хранение заявок.

SQLite, потому что заявок у малого бизнеса — десятки в день, а не
тысячи в секунду, и отдельная база данных здесь была бы лишней
сущностью, которую клиенту потом кто-то должен обслуживать.

Соединение открывается на каждую операцию. Это чуть медленнее и
заметно надёжнее: нет общего состояния между корутинами и нечему
ломаться при переподключении.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    created_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at DESC);
"""


@dataclass(frozen=True)
class Lead:
    id: int
    user_id: int
    username: Optional[str]
    created_at: str
    data: Dict[str, Any]

    @property
    def contact(self) -> str:
        return f"@{self.username}" if self.username else f"id{self.user_id}"

    def as_text(self) -> str:
        """Как заявка выглядит в уведомлении владельцу."""
        lines = [f"Заявка №{self.id} — {self.created_at}", f"От: {self.contact}", ""]
        lines += [f"{key}: {value}" for key, value in self.data.items()]
        return "\n".join(lines)


class Storage:
    def __init__(self, path: str = "leads.db"):
        self.path = path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add(self, user_id: int, username: Optional[str], data: Dict[str, Any]) -> Lead:
        created = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        payload = json.dumps(data, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO leads (user_id, username, created_at, payload) "
                "VALUES (?, ?, ?, ?)",
                (user_id, username, created, payload),
            )
            lead_id = cursor.lastrowid
        return Lead(lead_id, user_id, username, created, data)

    def _row_to_lead(self, row: sqlite3.Row) -> Lead:
        return Lead(
            id=row["id"],
            user_id=row["user_id"],
            username=row["username"],
            created_at=row["created_at"],
            data=json.loads(row["payload"]),
        )

    def recent(self, limit: int = 10) -> List[Lead]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_lead(r) for r in rows]

    def get(self, lead_id: int) -> Optional[Lead]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return self._row_to_lead(row) if row else None

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    def count_since(self, date_prefix: str) -> int:
        """Сколько заявок начиная с даты в формате YYYY-MM-DD."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM leads WHERE created_at >= ?", (date_prefix,)
            ).fetchone()[0]

    def export_csv(self, path: str) -> int:
        """Выгрузить все заявки. Возвращает число строк.

        Колонки собираются по всем заявкам, а не по первой: сценарий
        мог меняться, и старые заявки не должны терять поля.
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM leads ORDER BY id").fetchall()

        leads = [self._row_to_lead(r) for r in rows]

        fields: List[str] = []
        for lead in leads:
            for key in lead.data:
                if key not in fields:
                    fields.append(key)

        header = ["id", "Дата", "Контакт"] + fields
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            # utf-8-sig: без BOM Excel открывает кириллицу кракозябрами,
            # и клиент решает, что выгрузка сломана.
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(header)
            for lead in leads:
                writer.writerow(
                    [lead.id, lead.created_at, lead.contact]
                    + [lead.data.get(f, "") for f in fields]
                )
        return len(leads)
