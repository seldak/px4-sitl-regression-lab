from __future__ import annotations

import codecs
import os
import re
import select
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional


DEFAULT_MAX_LOG_BYTES = 20 * 1024 * 1024
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PXH_REDRAW_RE = re.compile(r"(?:\rpxh> ?)+")


def _clean_console_text(text: str) -> str:
    text = _ANSI_ESCAPE_RE.sub("", text)
    return _PXH_REDRAW_RE.sub("", text)


def _capture_stream(
    stream: BinaryIO,
    path: Path,
    max_bytes: int,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Drain process output while writing a bounded, plain-text diagnostic log."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    carry = ""
    written = 0
    truncated = False

    with open(path, "wb") as output:
        while stop_event is None or not stop_event.is_set():
            try:
                if stop_event is None:
                    chunk = stream.read(64 * 1024)
                else:
                    readable, _, _ = select.select([stream.fileno()], [], [], 0.2)
                    if not readable:
                        continue
                    chunk = os.read(stream.fileno(), 64 * 1024)
            except (OSError, ValueError):
                break
            if not chunk:
                break

            text = carry + decoder.decode(chunk)
            if len(text) <= 64:
                carry = text
                continue
            text, carry = text[:-64], text[-64:]

            cleaned = _clean_console_text(text).encode("utf-8")
            remaining = max(0, max_bytes - written)
            if remaining:
                output.write(cleaned[:remaining])
                output.flush()
                written += min(len(cleaned), remaining)
            if len(cleaned) > remaining:
                truncated = True

        cleaned = _clean_console_text(carry + decoder.decode(b"", final=True)).encode("utf-8")
        remaining = max(0, max_bytes - written)
        if remaining:
            output.write(cleaned[:remaining])
            written += min(len(cleaned), remaining)
        if len(cleaned) > remaining:
            truncated = True

        if truncated:
            output.write(
                f"\n[log truncated after {max_bytes} bytes; process output was still drained]\n".encode()
            )
        output.flush()


@dataclass
class SITLProcess:
    px4_dir: Path
    headless: bool
    stdout_path: Path
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES

    proc: Optional[subprocess.Popen] = None
    _capture_thread: Optional[threading.Thread] = None
    _capture_stop: Optional[threading.Event] = None

    def start(self) -> None:
        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.setdefault("PX4_SIM_MODEL", "iris")
        if self.headless:
            env["HEADLESS"] = "1"

        # Extra safety for headless rendering environments
        env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

        cmd = ["bash", "-lc", "make px4_sitl_default jmavsim"]

        self.proc = subprocess.Popen(
            cmd,
            cwd=str(self.px4_dir),
            env=env,
            # Keeping the pipe open prevents PX4's interactive shell from
            # reading EOF and redrawing `pxh>` in a tight loop on CI.
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group
        )
        if self.proc.stdout is None:
            raise RuntimeError("Failed to capture PX4 SITL output")
        self._capture_stop = threading.Event()
        self._capture_thread = threading.Thread(
            target=_capture_stream,
            args=(self.proc.stdout, self.stdout_path, self.max_log_bytes, self._capture_stop),
            name="px4-sitl-log-capture",
            daemon=True,
        )
        self._capture_thread.start()

        # Give it a moment to spawn PX4 + simulator before we try to connect.
        time.sleep(2.0)

    def stop(self, timeout_s: float = 8.0) -> None:
        proc = self.proc
        if proc is None:
            self._finish_capture()
            return

        if proc.poll() is not None:
            self._finish_capture()
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
            self._finish_capture()
            return

        # 2) less polite
        _killpg(signal.SIGTERM)
        if self._wait(proc, 2.0):
            self._finish_capture()
            return

        # 3) kill
        _killpg(signal.SIGKILL)
        self._wait(proc, 1.0)
        self._finish_capture()

    @staticmethod
    def _wait(proc: subprocess.Popen, seconds: float) -> bool:
        t0 = time.time()
        while time.time() - t0 < seconds:
            if proc.poll() is not None:
                return True
            time.sleep(0.1)
        return proc.poll() is not None

    def _finish_capture(self) -> None:
        if self.proc is not None and self.proc.stdin is not None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        if self._capture_thread is not None:
            # A detached simulator child can retain the write end indefinitely.
            # Signal the select-based reader instead of closing its pipe from
            # this thread, which can deadlock on Python's buffered-reader lock.
            if self._capture_stop is not None:
                self._capture_stop.set()
            self._capture_thread.join(timeout=2.0)
            capture_stopped = not self._capture_thread.is_alive()
            self._capture_thread = None
            self._capture_stop = None
        else:
            capture_stopped = True
        if capture_stopped and self.proc is not None and self.proc.stdout is not None:
            try:
                self.proc.stdout.close()
            except Exception:
                pass
