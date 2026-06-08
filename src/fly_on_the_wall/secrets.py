from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from fly_on_the_wall.config import API_KEY_ENV_VARS

KEYRING_SERVICE = "fly-on-the-wall"
SecretSource = Literal["env", "keyring", "missing", "unknown"]


class SecretError(RuntimeError):
    """Raised when a secret cannot be stored or removed."""


@dataclass(frozen=True)
class SecretStatus:
    provider: str
    env_var: str | None
    source: SecretSource

    @property
    def available(self) -> bool:
        return self.source in {"env", "keyring"}


def get_api_key(provider: str) -> str | None:
    env_value = _get_env_key(provider)
    if env_value:
        return env_value
    return _get_keyring_key(provider)


def get_api_key_status(provider: str) -> SecretStatus:
    normalized = provider.lower()
    env_var = API_KEY_ENV_VARS.get(normalized)
    if env_var is None:
        return SecretStatus(provider=normalized, env_var=None, source="unknown")
    if os.environ.get(env_var):
        return SecretStatus(provider=normalized, env_var=env_var, source="env")
    if _get_keyring_key(normalized):
        return SecretStatus(provider=normalized, env_var=env_var, source="keyring")
    return SecretStatus(provider=normalized, env_var=env_var, source="missing")


def set_api_key(provider: str, value: str) -> None:
    normalized = _require_known_provider(provider)
    try:
        keyring.set_password(KEYRING_SERVICE, normalized, value)
    except KeyringError as exc:
        raise SecretError(f"Could not store {normalized} API key in OS keyring: {exc}") from exc


def remove_api_key(provider: str) -> None:
    normalized = _require_known_provider(provider)
    try:
        keyring.delete_password(KEYRING_SERVICE, normalized)
    except PasswordDeleteError:
        return
    except KeyringError as exc:
        raise SecretError(f"Could not remove {normalized} API key from OS keyring: {exc}") from exc


def known_providers() -> list[str]:
    return sorted(API_KEY_ENV_VARS)


def _get_env_key(provider: str) -> str | None:
    env_var = API_KEY_ENV_VARS.get(provider.lower())
    if env_var is None:
        return None
    return os.environ.get(env_var) or None


def _get_keyring_key(provider: str) -> str | None:
    normalized = provider.lower()
    if normalized not in API_KEY_ENV_VARS:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, normalized) or None
    except KeyringError:
        return None


def _require_known_provider(provider: str) -> str:
    normalized = provider.lower()
    if normalized not in API_KEY_ENV_VARS:
        raise SecretError(f"Unknown provider: {provider}")
    return normalized
