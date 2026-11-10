"""Разбор прогресса hashcat без --status-json (Ubuntu 22.04 везёт 6.2.5)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.crack import Crack, _parse_text_status  # noqa: E402


class FakeCrack:
    def __init__(self):
        self.speed = ""
        self.progress = 0.0


class TextStatusTest(unittest.TestCase):
    LINE = ("Session..........: cracking\n"
            "Status...........: Running\n"
            "Hash.Target......: hash.hc22000\n"
            "Speed.#1.........:  1234.5 kH/s\n"
            "Progress.........: 512/2048 (25.00%)\n")

    def test_speed_and_progress(self):
        fake = FakeCrack()
        for line in self.LINE.splitlines():
            _parse_text_status(line, fake)  # type: ignore[arg-type]
        self.assertEqual(fake.speed, "1.2 MH/s")
        self.assertEqual(fake.progress, 25.0)

    def test_speed_without_multiplier(self):
        fake = FakeCrack()
        _parse_text_status("Speed.#2.........: 987 H/s", fake)  # type: ignore[arg-type]
        self.assertEqual(fake.speed, "987 H/s")

    def test_garbage_is_ignored(self):
        fake = FakeCrack()
        _parse_text_status("Recovered........: 0/1 (0.00%) Digests", fake)  # type: ignore[arg-type]
        self.assertEqual((fake.speed, fake.progress), ("", 0.0))

    def test_status_json_detection_is_a_bool(self):
        from core.base import which

        if not which("hashcat"):
            self.skipTest("hashcat не установлен")
        import tempfile

        crack = Crack.__new__(Crack)
        crack._json_ok = None
        self.assertIsInstance(Crack.supports_status_json(crack), bool)


if __name__ == "__main__":
    unittest.main()