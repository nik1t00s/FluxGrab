from __future__ import annotations

import json
from pathlib import Path


class HistoryStore:
    def __init__(self, app_name: str = "fluxgrab", limit: int = 10) -> None:
        self.limit = limit
        self.base_dir = Path.home() / f".{app_name}"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.base_dir / "history.json"

    def load(self) -> list[str]:
        if not self.history_file.exists():
            return []

        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        if isinstance(data, list):
            return [item for item in data if isinstance(item, str)]
        return []

    def add(self, url: str) -> list[str]:
        items = [item for item in self.load() if item != url]
        items.insert(0, url)
        items = items[: self.limit]
        self.history_file.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return items
