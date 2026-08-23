#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def oversized_files(root: Path, max_file_bytes: int) -> list[tuple[Path, int]]:
    if not root.exists():
        return []
    return [
        (path, path.stat().st_size)
        for path in root.rglob("*")
        if path.is_file() and path.stat().st_size > max_file_bytes
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject unexpectedly large run artifacts")
    parser.add_argument("root", type=Path)
    parser.add_argument("--max-file-mb", type=int, default=50)
    args = parser.parse_args()

    limit = args.max_file_mb * 1024 * 1024
    oversized = oversized_files(args.root, limit)
    for path, size in oversized:
        print(f"::error file={path}::{size} bytes exceeds the {args.max_file_mb} MiB artifact limit")
    return 1 if oversized else 0


if __name__ == "__main__":
    raise SystemExit(main())
