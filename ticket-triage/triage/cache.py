"""Remembers model answers on disk so re-runs are free and fast.

Identical tickets (we have several copy-pasted ones) are only sent to the model once.
Only SUCCESSFUL answers are stored - failures are always retried next run.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class Cache:
    def __init__(self, path: Path, enabled: bool = True):
        self.enabled = enabled
        self.lock = threading.Lock()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(path), check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, value TEXT)")
            self.db.commit()

    def get(self, key: str):
        if not self.enabled:
            return None
        with self.lock:
            row = self.db.execute("SELECT value FROM answers WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?)", (key, json.dumps(value)))
            self.db.commit()
