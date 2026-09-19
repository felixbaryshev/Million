import pytest

from bot.config import Config, ConfigError


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("BOT_TOKEN", "ADMIN_IDS", "SCENARIO_PATH", "DB_PATH"):
        monkeypatch.delenv(key, raising=False)


def test_a_missing_token_explains_where_to_get_one(monkeypatch):
    with pytest.raises(ConfigError, match="BotFather"):
        Config.from_env()


def test_a_missing_admin_list_explains_why_it_matters(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    with pytest.raises(ConfigError, match="некому получать заявки"):
        Config.from_env()


def test_a_non_numeric_admin_id_is_caught_at_startup(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ADMIN_IDS", "@ivan")
    with pytest.raises(ConfigError, match="userinfobot"):
        Config.from_env()


@pytest.mark.parametrize("raw,expected", [
    ("123", [123]), ("123,456", [123, 456]),
    ("123, 456", [123, 456]), ("123;456", [123, 456]),
])
def test_admin_ids_accept_the_usual_separators(monkeypatch, raw, expected):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ADMIN_IDS", raw)
    assert Config.from_env().admins == expected


def test_paths_fall_back_to_working_defaults(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ADMIN_IDS", "1")
    config = Config.from_env()
    assert config.scenario_path == "scenario.yaml"
    assert config.db_path == "leads.db"
