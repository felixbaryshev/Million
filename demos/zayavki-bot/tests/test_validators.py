import pytest

from bot.validators import (
    looks_like_junk, match_choice, normalize_phone, parse_number, validate_email,
)


@pytest.mark.parametrize("raw", [
    "89161234567", "+7 916 123-45-67", "8 (916) 123 45 67",
    "9161234567", "+79161234567", "  8-916-123-45-67  ",
])
def test_russian_numbers_normalise_to_one_form(raw):
    assert normalize_phone(raw) == "+79161234567"


@pytest.mark.parametrize("raw", ["", None, "   ", "abc", "12345", "8916123456789"])
def test_obvious_non_numbers_are_rejected(raw):
    assert normalize_phone(raw) is None


def test_a_landline_without_area_code_is_not_passed_off_as_mobile():
    assert normalize_phone("4951234567") is None


def test_an_international_number_is_kept_as_entered():
    assert normalize_phone("+380501234567") == "+380501234567"


def test_an_international_number_of_implausible_length_is_rejected():
    assert normalize_phone("+1234567890123456789") is None


@pytest.mark.parametrize("raw,expected", [
    ("User@Example.COM", "user@example.com"),
    (" a.b@mail.ru ", "a.b@mail.ru"),
])
def test_email_is_normalised(raw, expected):
    assert validate_email(raw) == expected


@pytest.mark.parametrize("raw", ["", "no-at-sign", "a@b", "a@@b.ru", "a b@c.ru"])
def test_malformed_email_is_rejected(raw):
    assert validate_email(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("1500", 1500.0), ("1 500", 1500.0), ("1500,50", 1500.5),
    ("1500.5", 1500.5), (" 42 ", 42.0),
])
def test_numbers_are_parsed_the_way_people_write_them(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "много", "1500 рублей", None])
def test_non_numbers_are_rejected(raw):
    assert parse_number(raw) is None


def test_a_choice_matches_by_text_case_insensitively():
    assert match_choice("ДОСТАВКА", ["Доставка", "Самовывоз"]) == "Доставка"


def test_a_choice_matches_by_position():
    assert match_choice("2", ["Доставка", "Самовывоз"]) == "Самовывоз"


def test_a_choice_outside_the_list_is_rejected():
    assert match_choice("Почтой", ["Доставка", "Самовывоз"]) is None
    assert match_choice("3", ["Доставка", "Самовывоз"]) is None


@pytest.mark.parametrize("raw", ["", " ", "?", "...", "-"])
def test_junk_answers_are_caught(raw):
    assert looks_like_junk(raw)


@pytest.mark.parametrize("raw", ["Нужен сайт", "ок", "10 штук"])
def test_real_answers_are_not_caught(raw):
    assert not looks_like_junk(raw)
