import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import portal  # noqa: E402

TPL = """<html><body>
<h1>{{TITLE}}</h1><p>Сеть {{SSID}} от {{VENDOR}}</p>
<form action="{{ACTION}}" method="post">
<input name="password" type="password">
<input name="login">
<button type="submit">ok</button></form>
<img src="{{STATIC}}logo.svg">
</body></html>"""


class PortalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "portals"
        (root / "tpl").mkdir(parents=True)
        (root / "tpl" / "index.html").write_text(TPL)
        (root / "tpl" / "meta.json").write_text(
            '{"name":"Тест","lang":"ru","title":"Роутер","steps":["index.html"],"fields":["password"]}')
        (root / "tpl" / "logo.svg").write_text("<svg/>")
        self._old = portal.PORTALS_DIR
        portal.PORTALS_DIR = root
        self.portal = portal.Portal("tpl", ssid="Дом <b>", vendor="tp-link")

    def tearDown(self):
        portal.PORTALS_DIR = self._old
        self.tmp.cleanup()

    def test_render_substitutes_and_escapes(self):
        body = self.portal.render(0).decode()
        self.assertIn("Роутер", body)
        self.assertIn("Дом &lt;b&gt;", body)
        self.assertNotIn("{{", body)
        self.assertIn("/static/logo.svg", body)

    def test_verdict_ok_keeps_last_step(self):
        self.portal.verifier = lambda fields: "ok" if fields.get("password") == "secret" else "retry"
        self.assertEqual(self.portal.accept({"password": "nope"}, "ua"), "retry")
        self.assertEqual(self.portal.verdict, "retry")
        self.assertEqual(self.portal.accept({"password": "secret"}, "ua"), "ok")
        self.assertEqual(len(self.portal.submissions), 2)

    def test_accept_without_verifier_is_pending(self):
        self.assertEqual(self.portal.accept({"password": "x"}, "ua"), "pending")

    def test_static_path_traversal(self):
        self.assertIsNotNone(self.portal.static_path("logo.svg"))
        self.assertIsNone(self.portal.static_path("../../etc/passwd"))

    def test_install_custom_requires_password_field(self):
        good = Path(self.tmp.name) / "good.html"
        good.write_text(TPL)
        meta = portal.install_custom(good, "Мой шаблон")
        self.assertIn("password", meta["fields"])

        bad = Path(self.tmp.name) / "bad.html"
        bad.write_text("<form><input name=user></form>")
        with self.assertRaises(portal.WilfiError):
            portal.install_custom(bad, "Без пароля")

    def test_template_listing(self):
        items = portal.list_templates()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "tpl")


if __name__ == "__main__":
    unittest.main()
