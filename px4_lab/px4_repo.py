from __future__ import annotations

import os
import subprocess
from pathlib import Path


def ensure_px4_repo(
    repo_root: Path,
    px4_dir: Path,
    tag: str,
    remote: str,
) -> None:
    """Fetch PX4 into px4_dir if needed, pinned to tag."""
    scripts_dir = repo_root / "scripts"
    fetch_script = scripts_dir / "fetch_px4.sh"

    if os.environ.get("PX4_SKIP_FETCH") == "1":
        print("[fetch_px4] PX4_SKIP_FETCH=1, skipping repo ensure.", flush=True)
        return

    if not fetch_script.exists():
        raise FileNotFoundError(f"Missing fetch script: {fetch_script}")

    env = os.environ.copy()
    env["PX4_DIR"] = str(px4_dir)
    env["PX4_TAG"] = tag
    env["PX4_REMOTE"] = remote

    subprocess.check_call(["bash", str(fetch_script)], cwd=str(repo_root), env=env)
