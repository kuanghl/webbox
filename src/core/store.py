"""Per-user settings persistence (JSON files).

Settings are stored under ``<data_dir>/<user>.json`` so multiple simulated
users keep independent API keys, language, theme and defaults. The active
user is tracked in ``_active_user.json`` in the same directory.

All frontends read/write user preferences through this module only
(AGENTS.md 3.5).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .constants import DEFAULT_USER, USERS

logger = logging.getLogger(__name__)

_ACTIVE_FILE = "_active_user.json"

#: Provider display name → (default model, default base_url).
PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "OpenAI": ("gpt-4o-mini", "https://api.openai.com/v1"),
    "DeepSeek": ("deepseek-chat", "https://api.deepseek.com/v1"),
    "Google": ("gemini-2.0-flash", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "Ollama": ("qwen2.5:7b", "http://localhost:11434/v1"),
    "OpenRouter": ("openai/gpt-4o-mini", "https://openrouter.ai/api/v1"),
    "Zhipu": ("glm-4-flash", "https://open.bigmodel.cn/api/paas/v4"),
    "Moonshot": ("moonshot-v1-8k", "https://api.moonshot.cn/v1"),
    "SiliconFlow": ("deepseek-ai/DeepSeek-V3", "https://api.siliconflow.cn/v1"),
    "OpenAI-compatible": ("", ""),
}


@dataclass
class UserSettings:
    """Persisted preferences of one simulated user.

    Attributes:
        user: Account name (key in the settings file).
        language: UI language code (``en``/``zh``).
        theme: Theme name (``light``/``dark``).
        provider: Default translation provider name.
        model: Default model name.
        api_key: Default API key (may be empty for local providers).
        base_url: Default provider base URL.
    """

    user: str = DEFAULT_USER
    language: str = "en"
    theme: str = "dark"
    provider: str = "DeepSeek"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"

    def __post_init__(self) -> None:
        if self.user not in USERS:
            self.user = DEFAULT_USER


class SettingsStore:
    """File-backed store of :class:`UserSettings` per user.

    Thread-safe for the single-process frontends (a lock guards read-modify
    write of the active user file).
    """

    def __init__(self, data_dir: Path) -> None:
        """Initialize the store.

        Args:
            data_dir: Directory holding per-user JSON files (created).
        """
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, user: str) -> Path:
        """Return the settings file path for a user."""
        return self._dir / f"{user}.json"

    def load(self, user: str | None = None) -> UserSettings:
        """Load settings for a user (or the active user).

        Args:
            user: Account name; ``None`` means the active user.

        Returns:
            The settings, falling back to defaults when the file is
            missing or corrupt.
        """
        user = user or self.active_user()
        path = self._path(user)
        if not path.exists():
            return UserSettings(user=user)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            known = {f for f in UserSettings.__dataclass_fields__}
            data = {k: v for k, v in raw.items() if k in known and k != "user"}
            return UserSettings(user=user, **data)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Corrupt settings file %s (%s); using defaults", path, exc)
            return UserSettings(user=user)

    def save(self, settings: UserSettings) -> None:
        """Persist settings for a user.

        Args:
            settings: The settings to write (atomic replace).
        """
        path = self._path(settings.user)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(settings.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        logger.info("Saved settings for user %s", settings.user)

    def active_user(self) -> str:
        """Return the currently active user name.

        Returns:
            The active user, or :data:`DEFAULT_USER` when unset.
        """
        path = self._dir / _ACTIVE_FILE
        if not path.exists():
            return DEFAULT_USER
        try:
            user = json.loads(path.read_text(encoding="utf-8")).get("user", DEFAULT_USER)
            return user if user in USERS else DEFAULT_USER
        except (json.JSONDecodeError, AttributeError):
            return DEFAULT_USER

    def set_active_user(self, user: str) -> None:
        """Switch the active user and persist the choice.

        Args:
            user: Account name to activate.
        """
        with self._lock:
            (self._dir / _ACTIVE_FILE).write_text(
                json.dumps({"user": user}), encoding="utf-8"
            )
        logger.info("Active user switched to %s", user)

    @staticmethod
    def provider_defaults(provider: str) -> tuple[str, str]:
        """Return ``(default_model, default_base_url)`` for a provider.

        Args:
            provider: Provider display name.

        Returns:
            The default model and base URL (empty strings when unknown).
        """
        return PROVIDER_DEFAULTS.get(provider, ("", ""))
