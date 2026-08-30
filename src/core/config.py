"""Application configuration via environment variables.

Uses ``pydantic-settings`` with the ``WEBBOX_`` env prefix, e.g.::

    WEBBOX_HOST=0.0.0.0 WEBBOX_PORT=9000 WEBBOX_LOG_LEVEL=DEBUG
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Runtime configuration for all webbox frontends.

    Attributes:
        host: Bind address for web frontends (NiceGUI/Flet).
        port: Bind port for web frontends.
        log_level: Root log level name (DEBUG..CRITICAL).
        log_dir: Directory for daily-rotated log files.
        data_dir: Directory for per-user settings JSON files.
            Defaults to ``~/.config/babeldoc-webui``.
    """

    model_config = SettingsConfigDict(env_prefix="WEBBOX_")

    host: str = "127.0.0.1"
    port: int = 8080
    log_level: str = "INFO"
    log_dir: Path = Path("logs")
    data_dir: Path | None = None

    def resolved_data_dir(self) -> Path:
        """Return the settings directory, creating it if needed.

        Returns:
            Absolute path of the per-user settings root.
        """
        path = self.data_dir or Path.home() / ".config" / "babeldoc-webui"
        path.mkdir(parents=True, exist_ok=True)
        return path
