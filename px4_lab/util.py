from __future__ import annotations

import datetime as _dt
from pathlib import Path


def utc_timestamp() -> str:
    # Colons are rejected in file paths by actions/upload-artifact.
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def newest_file_by_mtime(root: Path, pattern: str) -> Path | None:
    candidates = list(root.rglob(pattern))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[0]
