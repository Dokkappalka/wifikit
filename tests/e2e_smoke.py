"""End-to-end дым: поднимаем демон, дёргаем RPC по-настоящему.

Гоняется и на не-Linux (WIFIKIT_ALLOW_NONROOT=1), где часть вызовов вернёт ошибку —
важно, что демон не падает и отдаёт корректные конверты ошибок.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.base import WilfiError  # noqa: E402
from daemon.rpc import Client, socket_path  # noqa: E402


def wait_socket(path: Path, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                with socket.socket(socket.AF_UNIX) as s:
                    s.connect(str(path))
                return True
            except OSError:
                pass
        time.sleep(0.2)
    return False


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="wifikit-e2e-")
    os.environ["XDG_RUNTIME_DIR"] = tmp
    env = {**os.environ, "WIFIKIT_ALLOW_NONROOT": "1", "WIFIKIT_STATE_DIR": tmp,
           "WIFIKIT_PROJECTS_DIR": f"{tmp}/projects", "XDG_RUNTIME_DIR": tmp}
    proc = subprocess.Popen([sys.executable, str(ROOT / "daemon" / "main.py")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    failures = []
    try:
        path = socket_path()
        if not wait_socket(path):
            proc.terminate()
            try:
                out = proc.communicate(timeout=10)[0]
            except subprocess.TimeoutExpired:
                proc.kill()
                out = ""
            print("демон не поднялся:\n" + (out or ""))
            return 1
        client = Client(timeout=30)

        pong = client.call("ping")
        assert pong["pong"] is True
        print("ping ok")

        deps = client.call("deps_check")
        assert "deps" in deps and isinstance(deps["deps"], list)
        print(f"deps_check ok (missing: {len(deps['missing'])})")

        adapters = client.call("adapters_list")
        assert "adapters" in adapters
        print(f"adapters_list ok ({len(adapters['adapters'])} шт.)")

        templates = client.call("portal_templates")
        assert isinstance(templates["templates"], list)
        print(f"portal_templates ok ({len(templates['templates'])} шт.)")

        project = client.call("project_new", name="e2e тест")
        assert project["name"] == "e2e тест"
        print(f"project_new ok -> {project['path']}")

        client.call("project_note", text="заметка из теста")
        state = client.call("snapshot")
        assert state["project"]["name"] == "e2e тест"
        print("snapshot ok")

        try:
            client.call("capture_start", bssid="aa:bb:cc:dd:ee:ff")
            failures.append("capture_start без цели должен падать")
        except WilfiError as exc:
            print(f"capture без цели: {exc.code} — верно")

        report = client.call("report_export", fmt="md")
        assert Path(report["path"]).is_file()
        print(f"report_export ok -> {report['path']}")

        client.call("shutdown")
        print("shutdown ok")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    if failures:
        print("ПРОВАЛЫ:", failures)
        return 1
    print("E2E PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
