"""Установка не должна создавать условия для падений Qt.

История: GUI падал с SIGSEGV/SIGBUS. Две причины, которые ловятся здесь:
переполненный диск (pip кладёт обрезанные .so) и смешивание системного Qt6
с тем, что поставляется внутри PySide6.
"""

import os
import stat
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "packaging" / "install.sh"
DOCTOR = ROOT / "packaging" / "wifikit-doctor"


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.text = INSTALL.read_text()

    def test_no_system_qt_alongside_pyside(self):
        qt_line = [l for l in self.text.splitlines() if l.startswith("APT_QT=")]
        self.assertTrue(qt_line)
        joined = " ".join(qt_line)
        self.assertNotIn("libqt6svg6", joined, "системный Qt6 конфликтует с Qt внутри PySide6")

    def test_keeps_xcb_libraries(self):
        self.assertIn("libxcb-cursor0", self.text)
        self.assertIn("libxkbcommon-x11-0", self.text)

    def test_disk_space_guard(self):
        self.assertIn("df -Pm", self.text)
        self.assertIn("1200", self.text)

    def test_qt_smoke_test_present(self):
        self.assertIn("qt_smoke", self.text)
        self.assertIn("QT_QPA_PLATFORM=offscreen", self.text)

    def test_pyside_fallback_pin(self):
        self.assertIn("6.8.3", self.text)

    def test_installs_doctor(self):
        self.assertIn("wifikit-doctor", self.text)


class CrashToolTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "packaging" / "wifikit-crash").read_text()

    def test_extracts_apport_core(self):
        # apport хранит core как gzip в base64: без gunzip eu-stack получит мусор
        self.assertIn("CoreDump:", self.text)
        self.assertIn("base64 -d", self.text)
        self.assertIn("gzip -dc", self.text)

    def test_uses_eu_stack_not_gdb(self):
        self.assertIn("eu-stack", self.text)
        self.assertNotIn("gdb -q -batch", self.text)

    def test_explains_signal_codes(self):
        for code in ("SIGBUS", "SIGSEGV"):
            self.assertIn(code, self.text)


class DoctorTest(unittest.TestCase):
    def test_exists_and_executable(self):
        self.assertTrue(DOCTOR.is_file())
        self.assertTrue(DOCTOR.stat().st_mode & stat.S_IXUSR)

    def test_shebang(self):
        self.assertEqual(DOCTOR.read_bytes().split(b"\n", 1)[0], b"#!/bin/sh")

    def test_collects_what_matters(self):
        text = DOCTOR.read_text()
        for needle in ("df -h", "df -i", "free -m", "PySide6", "ldd", "offscreen",
                       "--check", "daemon.log", "virtiofs", "dmesg"):
            self.assertIn(needle, text, f"доктор не собирает {needle}")

    def test_no_sourcing_of_missing_os_release(self):
        # `.` несуществующего файла роняет POSIX-shell: проверка обязана быть в if
        text = DOCTOR.read_text()
        self.assertNotIn("\n  . /etc/os-release 2>/dev/null", text)


if __name__ == "__main__":
    unittest.main()