from __future__ import annotations

import re
import unittest

from px4_lab.util import utc_timestamp


class TimestampTests(unittest.TestCase):
    def test_timestamp_is_utc_and_artifact_path_safe(self) -> None:
        timestamp = utc_timestamp()

        self.assertRegex(timestamp, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$"))
        self.assertNotIn(":", timestamp)


if __name__ == "__main__":
    unittest.main()
