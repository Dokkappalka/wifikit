"""UI-гигиена: никаких модальных диалогов и незащищённых слотов.

История: QMessageBox с WA_DeleteOnClose удалял C++-объект под живой Python-обёрткой
(падение после закрытия), а исключение из слота (KeyError: 'deps') роняло процесс
целиком. Здесь это зафиксировано как свойство кода.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"


def sources() -> dict[str, str]:
    return {p.name: p.read_text() for p in APP.glob("*.py")}


def identifiers(path: Path) -> set[str]:
    """Имена и атрибуты, реально использованные в коде (без докстрингов и строк)."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                found.add(alias.name.split(".")[-1])
    return found


class NoModalDialogsTest(unittest.TestCase):
    def test_no_message_box(self):
        for path in APP.glob("*.py"):
            self.assertNotIn("QMessageBox", identifiers(path),
                             f"{path.name}: модальные окна роняли процесс")

    def test_no_delete_on_close(self):
        for path in APP.glob("*.py"):
            self.assertNotIn("WA_DeleteOnClose", identifiers(path),
                             f"{path.name}: удаление C++-объекта под живой обёрткой")


class SlotsGuardedTest(unittest.TestCase):
    def test_pages_wrap_callbacks(self):
        text = (APP / "pages.py").read_text()
        self.assertIn("safe_callback", text)
        self.assertNotIn("task.done.connect(on_done)", text)

    def test_main_uses_decoration(self):
        text = (APP / "main.py").read_text()
        self.assertGreaterEqual(text.count("@safe_slot"), 4)

    def test_payload_shape_checked(self):
        pages = (APP / "pages.py").read_text()
        main = (APP / "main.py").read_text()
        self.assertIn("expect_dict", pages)
        self.assertIn("expect_dict", main)


class NoAdviceTest(unittest.TestCase):
    def test_no_adapter_recommendations(self):
        adapters = (ROOT / "core" / "adapters.py").read_text()
        session = (ROOT / "daemon" / "session.py").read_text()
        self.assertNotIn("RECOMMENDED_CHIPS", adapters)
        self.assertNotIn("recomendations", adapters)
        self.assertNotIn('"recommended"', session)

    def test_no_diagnostics_page(self):
        pages = (APP / "pages.py").read_text()
        self.assertNotIn("class DiagPage", pages)
        self.assertNotIn('"diag"', pages)


class DialogsTest(unittest.TestCase):
    def test_dialogs_keep_reference(self):
        text = (APP / "dialogs.py").read_text()
        self.assertIn("class ErrorDialog", text)
        self.assertIn("class TextDialog", text)

    def test_main_keeps_dialog_refs(self):
        text = (APP / "main.py").read_text()
        self.assertIn("self._dialogs.append", text)
        self.assertNotIn("QInputDialog", text)

    def test_no_layout_shifting_banner(self):
        text = (APP / "main.py").read_text()
        self.assertNotIn("Banner(", text)


if __name__ == "__main__":
    unittest.main()