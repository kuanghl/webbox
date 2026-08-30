"""Unit tests for core config, i18n and the per-user settings store."""

import json

import pytest

from src.core import i18n
from src.core.config import AppConfig
from src.core.constants import DEFAULT_USER
from src.core.store import SettingsStore, UserSettings


@pytest.fixture(autouse=True)
def _reset_language():
    """Keep the global i18n language deterministic across tests."""
    i18n.set_language("en")
    yield
    i18n.set_language("en")


# ---------------------------------------------------------------- i18n ----

def test_i18n_default_english() -> None:
    assert i18n.tr("app.name") == "BabelDOC WebBox"
    assert i18n.tr("nav.translate") == "Translate"


def test_i18n_chinese_switch() -> None:
    i18n.set_language("zh")
    assert i18n.get_language() == "zh"
    assert i18n.tr("common.save") == "保存"
    assert i18n.tr("vram.estimate") == "估算"


def test_i18n_unknown_language_falls_back_to_en() -> None:
    i18n.set_language("xx")
    assert i18n.get_language() == "en"
    assert i18n.tr("app.name") == "BabelDOC WebBox"


def test_i18n_missing_key_returns_key() -> None:
    assert i18n.tr("no.such.key") == "no.such.key"


def test_i18n_kwargs_formatting() -> None:
    i18n.set_language("zh")
    assert i18n.tr("st.user_switched", user="bob") == "已切换到用户 bob"


# ------------------------------------------------------------- config -----

def test_config_defaults() -> None:
    config = AppConfig()
    assert config.host == "127.0.0.1"
    assert config.port == 8080
    assert config.log_level == "INFO"


def test_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBBOX_PORT", "9999")
    monkeypatch.setenv("WEBBOX_LOG_LEVEL", "DEBUG")
    config = AppConfig()
    assert config.port == 9999
    assert config.log_level == "DEBUG"


def test_config_resolved_data_dir(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    resolved = config.resolved_data_dir()
    assert resolved.is_dir()
    assert resolved == tmp_path / "data"


# -------------------------------------------------------------- store -----

def test_store_roundtrip(tmp_path) -> None:
    store = SettingsStore(data_dir=tmp_path)
    settings = store.load()
    settings.language = "zh"
    settings.theme = "light"
    settings.api_key = "sk-test"
    store.save(settings)

    reloaded = store.load()
    assert reloaded.language == "zh"
    assert reloaded.theme == "light"
    assert reloaded.api_key == "sk-test"


def test_store_corrupt_file_falls_back_to_defaults(tmp_path) -> None:
    (tmp_path / f"{DEFAULT_USER}.json").write_text("{not json")
    store = SettingsStore(data_dir=tmp_path)
    settings = store.load()
    assert settings.language == "en"
    assert settings.theme == "dark"


def test_store_unknown_user_field_ignored(tmp_path) -> None:
    (tmp_path / f"{DEFAULT_USER}.json").write_text(
        json.dumps({"language": "zh", "bogus_field": 1})
    )
    store = SettingsStore(data_dir=tmp_path)
    assert store.load().language == "zh"


def test_store_active_user_switch_persists(tmp_path) -> None:
    store = SettingsStore(data_dir=tmp_path)
    assert store.active_user() == DEFAULT_USER

    store.set_active_user("bob")
    assert store.active_user() == "bob"

    # a fresh store over the same dir sees the persisted active user
    assert SettingsStore(data_dir=tmp_path).active_user() == "bob"


def test_store_invalid_active_user_falls_back(tmp_path) -> None:
    (tmp_path / "_active_user.json").write_text(json.dumps({"user": "mallory"}))
    assert SettingsStore(data_dir=tmp_path).active_user() == DEFAULT_USER


def test_user_settings_rejects_unknown_user() -> None:
    settings = UserSettings(user="mallory")
    assert settings.user == DEFAULT_USER


def test_provider_defaults() -> None:
    model, url = SettingsStore.provider_defaults("OpenAI")
    assert model == "gpt-4o-mini"
    assert url == "https://api.openai.com/v1"
    assert SettingsStore.provider_defaults("Unknown") == ("", "")
