"""Портал по-настоящему: поднимаем сервер на петле и ходим по шагам."""

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import portal  # noqa: E402

TEMPLATES = [t["id"] for t in portal.list_templates()]


class PortalHttpTest(unittest.TestCase):
    def setUp(self):
        self.portal = portal.Portal("generic/two-step", ssid="CafeNet", vendor="generic")
        self.portal.verifier = lambda f: "ok" if f.get("password") == "right" else "retry"
        portal.serve(self.portal, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.portal.port}"

    def tearDown(self):
        portal.stop(self.portal)

    def _get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=5)

    def _post(self, fields):
        data = json.dumps(fields).encode()
        req = urllib.request.Request(self.base + "/submit", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:  # редиректы не должны превращаться в ошибку
            raise AssertionError(exc)

    def test_root_serves_step_one(self):
        body = self._get("/").read().decode()
        self.assertIn("CafeNet", body)
        self.assertIn("type=\"password\"", body.replace("'", '"'))

    def test_captive_probe_redirects(self):
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(self.base + "/generate_204", timeout=5)
        self.assertEqual(ctx.exception.code, 302)
        self.assertEqual(ctx.exception.headers["Location"], "/")

    def test_wrong_then_right(self):
        self.assertEqual(self._post({"password": "nope"})["verdict"], "retry")
        self.assertEqual(self._post({"password": "right"})["verdict"], "ok")
        self.assertEqual(len(self.portal.submissions), 2)
        self.assertEqual(self.portal.submissions[-1].verdict, "ok")

    def test_all_fields_are_stored(self):
        self._post({"room": "12", "surname": "Иванов", "password": "right"})
        sub = self.portal.submissions[-1]
        self.assertEqual(sub.fields["surname"], "Иванов")
        self.assertIn("password", sub.fields)

    def test_unknown_path_goes_to_portal(self):
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(self.base + "/some/captive/url", timeout=5)
        self.assertEqual(ctx.exception.code, 302)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AllTemplatesRenderTest(unittest.TestCase):
    def test_every_shipped_template_renders_both_steps(self):
        self.assertGreaterEqual(len(TEMPLATES), 6, "шаблонов должно быть не меньше шести")
        for template_id in TEMPLATES:
            p = portal.Portal(template_id, ssid="Тестовая сеть", vendor="x")
            for index in range(len(p.template.steps)):
                body = p.render(index).decode()
                self.assertIn("password", body.lower(), f"{template_id}: шаг {index} без поля пароля")
                self.assertNotIn("{{", body, f"{template_id}: остались плейсхолдеры")

    def test_templates_have_unique_ids(self):
        self.assertEqual(len(TEMPLATES), len(set(TEMPLATES)))


if __name__ == "__main__":
    unittest.main()
