import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import base, project, report  # noqa: E402
from daemon.rpc import Router  # noqa: E402


class ResourceSetTest(unittest.TestCase):
    def test_rollback_reverse_order(self):
        order = []
        rs = base.ResourceSet("t")
        rs.add("first", lambda: order.append(1))
        rs.add("second", lambda: order.append(2))
        problems = rs.rollback()
        self.assertEqual(order, [2, 1])
        self.assertEqual(problems, [])

    def test_failure_does_not_stop_rollback(self):
        order = []

        def boom():
            raise RuntimeError("x")

        rs = base.ResourceSet("t")
        rs.add("bad", boom)
        rs.add("good", lambda: order.append("ok"))
        problems = rs.rollback()
        self.assertEqual(order, ["ok"])
        self.assertEqual(len(problems), 1)
        self.assertIn("bad", problems[0])

    def test_double_rollback_is_noop(self):
        order = []
        rs = base.ResourceSet("t")
        rs.add("x", lambda: order.append(1))
        rs.rollback()
        rs.rollback()
        self.assertEqual(order, [1])

    def test_add_after_rollback_raises(self):
        rs = base.ResourceSet("t")
        rs.rollback()
        with self.assertRaises(base.WilfiError):
            rs.add("late", lambda: None)


class WaitTest(unittest.TestCase):
    def test_wait_until_true(self):
        flag = {"v": False}
        threading.Timer(0.1, lambda: flag.update(v=True)).start()
        self.assertTrue(base.wait_until(lambda: flag["v"], 2))

    def test_wait_until_timeout(self):
        start = time.monotonic()
        self.assertFalse(base.wait_until(lambda: False, 0.3, interval=0.05))
        self.assertLess(time.monotonic() - start, 2)


class JsonTest(unittest.TestCase):
    def test_atomic_write_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            base.atomic_write_json(path, {"a": 1})
            self.assertEqual(json.loads(path.read_text()), {"a": 1})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_read_missing_returns_default(self):
        self.assertEqual(base.read_json(Path("/nonexistent/x.json"), {"d": 1}), {"d": 1})


class ProjectTest(unittest.TestCase):
    def test_new_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project.new("Тест 1", base=Path(tmp))
            p.target = project.Target(bssid="aa:bb:cc:dd:ee:ff", ssid="net", channel=6)
            p.probe_iface = "wlan0"
            p.save()
            again = project.open_project(p.path)
            self.assertEqual(again.target.bssid, "aa:bb:cc:dd:ee:ff")
            self.assertEqual(again.probe_iface, "wlan0")
            self.assertEqual(len(project.list_projects(base=Path(tmp))), 1)

    def test_slug_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project.new("Дом / Wi-Fi!", base=Path(tmp))
            self.assertIn("wi-fi", p.path.name)
            self.assertNotIn(" ", p.path.name)

    def test_report_contains_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project.new("r", base=Path(tmp))
            p.target = project.Target(bssid="aa:bb:cc:dd:ee:ff", ssid="net", channel=6, wpa2=True)
            p.password = "secret123"
            md = report.build_markdown(p)
            self.assertIn("secret123", md)
            self.assertIn("net", md)
            html = report.build_html(p)
            self.assertIn("<h1>", html)
            self.assertIn("secret123", html)


class RouterTest(unittest.TestCase):
    class FakeSession:
        def __init__(self):
            self.lock = threading.RLock()
            self.calls = 0

        def ping(self):
            self.calls += 1
            return {"pong": True}

        def with_args(self, a: int = 0, b: int = 0):
            return {"sum": a + b}

        def boom(self):
            raise base.WilfiError("нет", code="nope")

        def crash(self):
            raise RuntimeError("kaput")

    def setUp(self):
        self.session = self.FakeSession()
        self.router = Router(self.session)

    def test_ping(self):
        res = self.router.dispatch({"id": 1, "method": "ping"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["id"], 1)

    def test_unknown_method(self):
        res = self.router.dispatch({"id": 2, "method": "nope"})
        self.assertEqual(res["error"]["code"], "no_method")

    def test_extra_params_are_dropped(self):
        res = self.router.dispatch({"id": 3, "method": "with_args", "params": {"a": 2, "b": 3, "zzz": 9}})
        self.assertEqual(res["data"], {"sum": 5})

    def test_wilfi_error_is_code(self):
        res = self.router.dispatch({"id": 4, "method": "boom"})
        self.assertEqual(res["error"]["code"], "nope")

    def test_crash_becomes_internal(self):
        res = self.router.dispatch({"id": 5, "method": "crash"})
        self.assertEqual(res["error"]["code"], "internal")
        self.assertIn("kaput", res["error"]["message"])


if __name__ == "__main__":
    unittest.main()
