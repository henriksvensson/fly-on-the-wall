import pytest
from keyring.errors import KeyringError

from fly_on_the_wall.secrets import (
    KEYRING_SERVICE,
    SecretError,
    get_api_key,
    get_api_key_status,
    known_providers,
    remove_api_key,
    set_api_key,
)


def test_get_api_key_prefers_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setattr("keyring.get_password", lambda service, provider: "keyring-key")

    assert get_api_key("openai") == "env-key"
    assert get_api_key_status("openai").source == "env"


def test_get_api_key_falls_back_to_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda service, provider: "keyring-key")

    assert get_api_key("openai") == "keyring-key"
    assert get_api_key_status("openai").source == "keyring"


def test_get_api_key_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda service, provider: None)

    assert get_api_key("openai") is None
    assert get_api_key_status("openai").source == "missing"


def test_set_api_key_stores_in_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_set_password(service: str, provider: str, value: str) -> None:
        calls.append((service, provider, value))

    monkeypatch.setattr("keyring.set_password", fake_set_password)

    set_api_key("openai", "secret")

    assert calls == [(KEYRING_SERVICE, "openai", "secret")]


def test_set_api_key_wraps_keyring_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_set_password(service: str, provider: str, value: str) -> None:
        raise KeyringError("no backend")

    monkeypatch.setattr("keyring.set_password", fake_set_password)

    with pytest.raises(SecretError, match="Could not store openai"):
        set_api_key("openai", "secret")


def test_remove_api_key_deletes_from_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_delete_password(service: str, provider: str) -> None:
        calls.append((service, provider))

    monkeypatch.setattr("keyring.delete_password", fake_delete_password)

    remove_api_key("openai")

    assert calls == [(KEYRING_SERVICE, "openai")]


def test_known_providers_includes_core_providers() -> None:
    assert known_providers() == ["elevenlabs", "openai"]
