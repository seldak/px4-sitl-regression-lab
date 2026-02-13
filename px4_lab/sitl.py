from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SITLProcess:
    px4_dir: Path
    headless: bool
    stdout_path: Path

    proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.setdefault("PX4_SIM_MODEL", "iris")
        if self.headless:
            env["HEADLESS"] = "1"

        # Extra safety for headless rendering environments
        env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

        cmd = ["bash", "-lc", "make px4_sitl_default jmavsim"]
        with open(self.stdout_path, "w", encoding="utf-8") as f:
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(self.px4_dir),
                env=env,
                stdout=f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,  # create a process group so we can kill children too
            )

        # Give it a moment to spawn PX4 + simulator before we try to connect.
        time.sleep(2.0)

    def stop(self, timeout_s: float = 10.0) -> None:
        if self.proc is None:
            return

        if self.proc.poll() is not None:
            return

        try:
            pgid = os.getpgid(self.proc.pid)
            os.killpg(pgid, signal.SIGINT)
        except ProcessLookupError:
            return

        try:
            self.proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                pgid = os.getpgid(self.proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait(timeout=timeout_s)
