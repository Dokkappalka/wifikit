"""Контракт запуска демона через pkexec.

pkexec делает execve() по пути из policy — значит файл обязан быть исполняемым
и начинаться с shebang. Отсутствие shebang ядро отдаёт как «Exec format error»,
и приложение видит только «демон не поднялся».
"""

import os
import stat
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DAEMON = ROOT / "daemon" / "main.py"
LAUNCHER = ROOT / "packaging" / "wifikit"


class DaemonEntrypointTest(unittest.TestCase):
    def test_starts_with_shebang(self):
        first = DAEMON.read_bytes().split(b"\n", 1)[0]
        self.assertEqual(first, b"#!/usr/bin/env python3",
                         "первая строка демона обязана быть shebang, иначе execve → ENOEXEC")

    def test_no_crlf(self):
        data = DAEMON.read_bytes()
        self.assertNotIn(b"\r\n", data, "CRLF в shebang ломает запуск")

    def test_is_executable_bit_in_repo(self):
        mode = DAEMON.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, "демон должен быть +x: chmod +x daemon/main.py")

    def test_policy_points_to_installed_path(self):
        policy = (ROOT / "packaging" / "io.github.wifikit.policy").read_text()
        self.assertIn("/usr/lib/wifikit/daemon.py", policy)

    def test_installer_copies_daemon_as_executable(self):
        text = (ROOT / "packaging" / "install.sh").read_text()
        self.assertIn("daemon/main.py", text)
        self.assertIn("0755", text)

    def test_launcher_uses_explicit_interpreter(self):
        text = LAUNCHER.read_text()
        self.assertIn('exec "$PY"', text)

    def test_self_check_mode_exists(self):
        text = DAEMON.read_text()
        self.assertIn("--check", text)
        self.assertIn("def self_check", text)

    @unittest.skipUnless(os.path.exists("/usr/bin/python3") or os.path.exists("/usr/local/bin/python3"),
                         "нет системного python3")
    def test_spawn_uses_explicit_interpreter(self):
        try:
            from app import remote as remote_mod
        except ModuleNotFoundError:
            self.skipTest("PySide6 не установлен")
        captured = {}

        class FakePopen:
            def __init__(self, argv, **kwargs):
                captured["argv"] = argv

        original = remote_mod.subprocess.Popen
        remote_mod.subprocess.Popen = FakePopen  # type: ignore[assignment]
        try:
            remote_mod.Remote()._spawn_daemon()
        finally:
            remote_mod.subprocess.Popen = original  # type: ignore[assignment]
        argv = captured["argv"]
        self.assertEqual(argv[0], "pkexec")
        self.assertTrue(argv[1].endswith("python3"), argv)
        self.assertIn("daemon", " ".join(argv))
        self.assertIn("--socket", argv)


if __name__ == "__main__":
    unittest.main()