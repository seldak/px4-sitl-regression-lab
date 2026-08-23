from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from px4_lab.sitl import _capture_stream
from scripts.check_artifact_sizes import oversized_files


class SITLLogCaptureTests(unittest.TestCase):
    def test_console_redraws_and_ansi_sequences_are_removed(self) -> None:
        source = io.BytesIO(
            b"PX4 ready\npxh> \x1b[2K\rpxh> \x1b[2K\rpxh> INFO [commander] armed\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sitl_stdout.log"
            _capture_stream(source, output, max_bytes=1024)
            text = output.read_text(encoding="utf-8")

        self.assertNotIn("\x1b", text)
        self.assertEqual(text.count("pxh>"), 1)
        self.assertIn("INFO [commander] armed", text)

    def test_log_is_capped_while_input_is_fully_drained(self) -> None:
        source = io.BytesIO(b"diagnostic line\n" * 100)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sitl_stdout.log"
            _capture_stream(source, output, max_bytes=64)
            text = output.read_text(encoding="utf-8")
            output_size = output.stat().st_size

        self.assertEqual(source.tell(), len(source.getvalue()))
        self.assertIn("log truncated after 64 bytes", text)
        self.assertLess(output_size, 160)


class ArtifactSizeTests(unittest.TestCase):
    def test_oversized_files_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "small.log").write_bytes(b"1234")
            (root / "large.log").write_bytes(b"12345")

            oversized = oversized_files(root, max_file_bytes=4)

        self.assertEqual([(path.name, size) for path, size in oversized], [("large.log", 5)])


if __name__ == "__main__":
    unittest.main()
