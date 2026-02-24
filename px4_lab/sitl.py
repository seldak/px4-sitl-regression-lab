from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TextIO


@dataclass
class SITLProcess:
    px4_dir: Path
    headless: bool
    stdout_path: Path

    proc: Optional[subprocess.Popen] = None
    _stdout_fh: Optional[TextIO] = None

    def start(self) -> None:
        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.setdefault("PX4_SIM_MODEL", "iris")
        if self.headless:
            env["HEADLESS"] = "1"

        # Extra safety for headless rendering environments
        env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

        cmd = ["bash", "-lc", "make px4_sitl_default jmavsim"]

        # IMPORTANT: keep this file handle open while the subprocess is running.
        self._stdout_fh = open(self.stdout_path, "w", encoding="utf-8")

        self.proc = subprocess.Popen(
            cmd,
            cwd=str(self.px4_dir),
            env=env,
            stdout=self._stdout_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group
        )

        # Give it a moment to spawn PX4 + simulator before we try to connect.
        time.sleep(2.0)

    def stop(self, timeout_s: float = 8.0) -> None:
        proc = self.proc
        if proc is None:
            self._close_stdout()
            return

        if proc.poll() is not None:
            self._close_stdout()
            return

        # Since we used start_new_session=True, the child is session leader => killpg(proc.pid, sig)
        def _killpg(sig: int) -> None:
            try:
                os.killpg(proc.pid, sig)
            except Exception:
                try:
                    proc.send_signal(sig)
                except Exception:
                    pass

        # 1) polite
        _killpg(signal.SIGINT)
        if self._wait(proc, timeout_s):
            self._close_stdout()
            return

        # 2) less polite
        _killpg(signal.SIGTERM)
        if self._wait(proc, 2.0):
            self._close_stdout()
            return

        # 3) kill
        _killpg(signal.SIGKILL)
        self._wait(proc, 1.0)
        self._close_stdout()

    @staticmethod
    def _wait(proc: subprocess.Popen, seconds: float) -> bool:
        t0 = time.time()
        while time.time() - t0 < seconds:
            if proc.poll() is not None:
                return True
            time.sleep(0.1)
        return proc.poll() is not None

    def _close_stdout(self) -> None:
        if self._stdout_fh is not None:
            try:
                self._stdout_fh.flush()
                self._stdout_fh.close()
            except Exception:
                pass
            self._stdout_fh = None

