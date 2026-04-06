"""Файловый кэш с TTL для сырья API и ответов (без БД)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional


class FileCache:
    def __init__(self, root: Path, default_ttl_sec: int = 3600):
        self.root = Path(root)
        self.default_ttl_sec = default_ttl_sec
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{h}.json"

    def get(self, key: str) -> Optional[Any]:
        p = self._path(key)
        if not p.is_file():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        exp = raw.get("_expires_at")
        if exp is not None and time.time() > float(exp):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        return raw.get("value")

    def set(self, key: str, value: Any, ttl_sec: Optional[int] = None) -> None:
        ttl = ttl_sec if ttl_sec is not None else self.default_ttl_sec
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "value": value,
            "_expires_at": time.time() + max(1, ttl),
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
