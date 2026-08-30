"""Application-wide constants.

Central place for UI languages, theme options, simulated users and the
source/target language list offered on the translation page.
"""

from __future__ import annotations

APP_NAME: str = "BabelDOC WebBox"
APP_TAGLINE: str = "PDF translation & LLM deployment toolkit"

#: UI interface languages supported by ``src.core.i18n``.
UI_LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh": "中文",
}

#: Theme options (mapped per-framework in ``src.core.theme``).
THEMES: dict[str, str] = {
    "light": "Light",
    "dark": "Dark",
}

#: Simulated multi-user accounts (AGENTS.md 3.5 user switching).
USERS: tuple[str, ...] = ("alice", "bob")
DEFAULT_USER: str = "alice"

#: Source/target languages for PDF translation (babeldoc language codes).
TRANSLATE_LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh": "中文 (Chinese)",
    "ja": "日本語 (Japanese)",
    "ko": "한국어 (Korean)",
    "fr": "Français (French)",
    "de": "Deutsch (German)",
    "es": "Español (Spanish)",
    "ru": "Русский (Russian)",
    "it": "Italiano (Italian)",
    "pt": "Português (Portuguese)",
    "ar": "العربية (Arabic)",
    "hi": "हिन्दी (Hindi)",
}

DEFAULT_LANG_IN: str = "en"
DEFAULT_LANG_OUT: str = "zh"
