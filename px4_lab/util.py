from __future__ import annotations

import datetime as _dt
from pathlib import Path


def utc_timestamp() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def newest_file_by_mtime(root: Path, pattern: str) -> Path | None:
    candidates = list(root.rglob(pattern))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[0]
