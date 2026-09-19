import csv

import pytest

from bot.storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "test.db"))


def test_a_saved_lead_comes_back_with_its_data(store):
    lead = store.add(1, "ivan", {"Имя": "Иван", "Телефон": "+79161234567"})
    assert lead.id == 1
    assert store.get(1).data["Имя"] == "Иван"


def test_ids_increment(store):
    assert store.add(1, "a", {"x": 1}).id == 1
    assert store.add(2, "b", {"x": 2}).id == 2


def test_recent_returns_newest_first(store):
    for i in range(5):
        store.add(i, f"u{i}", {"n": i})
    assert [lead.data["n"] for lead in store.recent(3)] == [4, 3, 2]


def test_count_tracks_inserts(store):
    assert store.count() == 0
    store.add(1, "a", {"x": 1})
    assert store.count() == 1


def test_a_missing_lead_is_none_not_an_error(store):
    assert store.get(999) is None


def test_a_user_without_a_username_is_still_identifiable(store):
    lead = store.add(42, None, {"x": 1})
    assert lead.contact == "id42"


def test_a_username_is_shown_with_an_at_sign(store):
    assert store.add(42, "ivan", {"x": 1}).contact == "@ivan"


def test_the_notification_text_lists_every_field(store):
    lead = store.add(1, "ivan", {"Имя": "Иван", "Телефон": "+79161234567"})
    text = lead.as_text()
    assert "Заявка №1" in text and "Иван" in text and "+79161234567" in text


def test_cyrillic_survives_a_round_trip(store):
    store.add(1, "u", {"Комментарий": "Нужно срочно, до пятницы"})
    assert store.get(1).data["Комментарий"] == "Нужно срочно, до пятницы"


def test_export_writes_every_lead(tmp_path, store):
    for i in range(3):
        store.add(i, f"u{i}", {"Имя": f"Клиент {i}"})
    out = tmp_path / "leads.csv"
    assert store.export_csv(str(out)) == 3
    rows = list(csv.reader(out.open(encoding="utf-8-sig"), delimiter=";"))
    assert len(rows) == 4
    assert rows[0] == ["id", "Дата", "Контакт", "Имя"]


def test_export_keeps_fields_from_older_scenarios(tmp_path, store):
    store.add(1, "a", {"Имя": "Иван"})
    store.add(2, "b", {"Имя": "Пётр", "Бюджет": "50000"})
    out = tmp_path / "leads.csv"
    store.export_csv(str(out))
    rows = list(csv.reader(out.open(encoding="utf-8-sig"), delimiter=";"))
    assert rows[0] == ["id", "Дата", "Контакт", "Имя", "Бюджет"]
    assert rows[1][-1] == ""


def test_export_is_written_with_a_bom_so_excel_reads_cyrillic(tmp_path, store):
    store.add(1, "a", {"Имя": "Иван"})
    out = tmp_path / "leads.csv"
    store.export_csv(str(out))
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")


def test_export_of_an_empty_base_still_writes_a_header(tmp_path, store):
    out = tmp_path / "leads.csv"
    assert store.export_csv(str(out)) == 0
    assert out.read_text(encoding="utf-8-sig").startswith("id;Дата;Контакт")


def test_reopening_the_database_keeps_the_leads(tmp_path):
    path = str(tmp_path / "persist.db")
    Storage(path).add(1, "a", {"x": 1})
    assert Storage(path).count() == 1
