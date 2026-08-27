"""翻译记录持久化：页面刷新后仍可下载/查看历史结果."""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_PATH = Path.home() / ".config" / "babeldoc-webui" / "history.json"


class HistoryManager:
    """管理持久化的翻译结果记录."""

    def __init__(self, config_path: Path | None = None):
        if config_path is None:
            config_path = DEFAULT_HISTORY_PATH
        self.config_path = config_path
        self._lock = threading.Lock()
        self._records: list[dict] = []
        self.load()

    def load(self) -> None:
        """从磁盘加载历史记录并过滤掉已不存在的文件."""
        with self._lock:
            try:
                data = json.loads(self.config_path.read_text("utf-8"))
                self._records = list(data.get("records", []))
            except (FileNotFoundError, json.JSONDecodeError, TypeError):
                self._records = []
            self._prune_missing(lock_held=True)

    def _prune_missing(self, lock_held: bool = False) -> None:
        """只保留文件仍然存在的记录."""
        records = [r for r in self._records if r.get("path") and Path(str(r["path"])).exists()]
        changed = len(records) != len(self._records)
        self._records = records
        if changed and not lock_held:
            self.save()

    def _save_locked(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.config_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps({"records": self._records}, ensure_ascii=False, indent=2),
            "utf-8",
        )
        tmp_path.replace(self.config_path)

    def save(self) -> None:
        """写回磁盘."""
        with self._lock:
            self._prune_missing(lock_held=True)
            try:
                self._save_locked()
            except Exception as e:
                logger.warning(f"Failed to save history: {e}")

    def add(self, record: dict) -> dict:
        """追加一条记录并保存."""
        record = dict(record)
        record.setdefault("id", uuid4_hex())
        record.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        with self._lock:
            self._records.append(record)
            try:
                self._save_locked()
            except Exception as e:
                logger.warning(f"Failed to save history: {e}")
        return record

    def records(self) -> list[dict]:
        """返回仍存在对应文件的记录列表（不包含已失效项）."""
        with self._lock:
            self._prune_missing(lock_held=True)
            return list(self._records)

    def clear(self) -> None:
        """清空全部历史记录."""
        with self._lock:
            self._records = []
            try:
                self._save_locked()
            except Exception as e:
                logger.warning(f"Failed to clear history: {e}")


def uuid4_hex() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


history_manager = HistoryManager()