"""Проверка потока: колбэки демона обязаны исполняться в потоке GUI.

Регрессия, которую это сторожит: результат фонового вызова отдавался сигналом
напрямую, Qt соединял его с обычной Python-функцией «напрямую», и обработчик
менял виджеты из рабочего потока. Это порча памяти и SIGSEGV через минуту-две
работы, а не «иногда подлагивает».
"""

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QCoreApplication, Qt
    HAS_QT = True
except ModuleNotFoundError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 не установлен")
class TaskThreadAffinityTest(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication([])

    def _run_task(self, result):
        from app.remote import Task

        class FakeRemote:
            def call(self, method, **params):
                return {"thread": threading.current_thread().name, "payload": result}

        seen = {}

        task = Task(FakeRemote(), "ping")
        main_thread = threading.current_thread().name

        def on_done(data):
            seen["thread"] = threading.current_thread().name
            seen["data"] = data
            seen["main"] = main_thread

        task.done.connect(on_done)
        task.start()
        deadline = time.monotonic() + 5
        while "thread" not in seen and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        return seen

    def test_callback_runs_in_gui_thread(self):
        seen = self._run_task("x")
        self.assertIn("thread", seen, "колбэк не вызван")
        self.assertEqual(seen["thread"], seen["main"],
                         "колбэк выполнился в рабочем потоке — это и есть причина SIGSEGV")
        self.assertEqual(seen["data"]["payload"], "x")

    def test_worker_thread_is_not_main(self):
        seen = self._run_task("y")
        self.assertNotEqual(seen["data"]["thread"], seen["main"])

    def test_queued_connection_declared(self):
        text = (ROOT / "app" / "remote.py").read_text()
        self.assertIn("Qt.QueuedConnection", text)


class FaulthandlerEnabledTest(unittest.TestCase):
    """Падение должно оставлять Python-трейсбек, а не только 'core dumped'."""

    def test_startup_enables_faulthandler(self):
        text = (ROOT / "app" / "main.py").read_text()
        self.assertIn("faulthandler", text)

    def test_launcher_sets_env(self):
        text = (ROOT / "packaging" / "wifikit").read_text()
        self.assertIn("PYTHONFAULTHANDLER", text)


if __name__ == "__main__":
    unittest.main()