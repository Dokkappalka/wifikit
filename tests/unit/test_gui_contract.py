"""Контракт между GUI и демоном: имена, которых нельзя менять молча.

История: метод `Remote.connect` на QObject перекрывал Qt-стиль
`QObject.connect(sender, signal, receiver, slot)` и приложение падало на
`self.remote.log.connect(...)` с «takes 1 to 2 positional arguments». Тест
сторожит, чтобы имя не вернулось.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    import PySide6  # noqa: F401

    HAS_QT = True
except ModuleNotFoundError:
    HAS_QT = False

REMOTE_METHODS = {"is_connected", "open_link", "call", "shutdown"}
SESSION_METHODS = {
    "ping", "deps_check", "adapters_list", "adapters_assign", "scan_start",
    "capture_start", "capture_status", "deauth_start", "ap_start", "ap_status",
    "portal_start", "portal_templates", "crack_start", "crack_status",
    "mask_preview", "project_new", "project_open", "report_export", "snapshot",
}


@unittest.skipUnless(HAS_QT, "PySide6 не установлен")
class RemoteApiTest(unittest.TestCase):
    def setUp(self):
        from app.remote import Remote

        self.Remote = Remote
        self.remote = Remote()

    def test_no_method_named_connect(self):
        # у QObject.connect есть свой статический метод — проверяем именно наш класс
        self.assertNotIn("connect", self.Remote.__dict__,
                         "метод connect на QObject ломает подключение сигналов — используйте open_link")

    def test_signals_are_signals(self):
        from PySide6.QtCore import SignalInstance

        self.assertIsInstance(self.remote.log, SignalInstance)
        self.assertIsInstance(self.remote.failed, SignalInstance)

    def test_signals_connect(self):
        received = []
        self.remote.log.connect(received.append)
        self.remote.log.emit("строка")
        self.assertEqual(received, ["строка"])

    def test_legacy_names_are_gone(self):
        self.assertNotIn("connected", self.Remote.__dict__)

    def test_remote_has_gui_methods(self):
        missing = [m for m in REMOTE_METHODS if not hasattr(self.Remote, m)]
        self.assertEqual(missing, [])

    def test_open_link_waits_for_daemon(self):
        # без демона метод обязан вернуться по таймауту, а не висеть вечно
        import time

        started = time.monotonic()
        self.remote.open_link(timeout=0.4)
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(self.remote.is_connected())


class SessionApiTest(unittest.TestCase):
    """У демона должен быть ровно тот набор методов, который зовёт GUI."""

    def test_session_has_gui_methods(self):
        from daemon.session import Session

        session = Session()
        missing = [m for m in SESSION_METHODS if not hasattr(session, m)]
        self.assertEqual(missing, [])

    def test_same_adapter_for_both_roles_refused(self):
        """Один адаптер не может быть и сенсором, и фейк-точкой."""
        from unittest import mock

        from core import adapters as adapters_mod
        from core.base import WilfiError
        from daemon.session import Session

        class FakeAdapter:
            iface = "wlx_fake"
            monitor = True
            ap = True
            rfkill_blocked = False

        session = Session()
        with mock.patch.object(adapters_mod, "get_adapter", lambda iface: FakeAdapter()):
            session.adapters_assign("probe", "wlx_test")
            with self.assertRaises(WilfiError):
                session.adapters_assign("ap", "wlx_test")
            session.adapters_assign("ap", "wlx_other")
        self.assertEqual((session.probe_iface, session.ap_iface), ("wlx_test", "wlx_other"))

    def test_role_cleared_by_empty_selection(self):
        from unittest import mock

        from core import adapters as adapters_mod
        from daemon.session import Session

        session = Session()
        with mock.patch.object(adapters_mod, "get_adapter", lambda iface: None):
            session.adapters_assign("probe", "wlx_test")
            session.adapters_assign("probe", "")
        self.assertEqual(session.probe_iface, "")

    def test_mutating_methods_are_declared(self):
        from daemon import rpc

        for method in ("ap_start", "capture_start", "crack_start", "shutdown"):
            self.assertIn(method, rpc.MUTATING)


if __name__ == "__main__":
    unittest.main()