"""Крошилка на hashcat -m 22000: словарь, правила, маска, гибрид.

Прогресс берётся из `--status-json` (машиночитаемо), результат — из `-o`.
Потифайл складывается в проект, поэтому перезапуск продолжает с места остановки.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .base import WilfiError, ensure_dir, require, run
from .jobs import Job, JobRegistry
from .mask import MaskSpec

RULES_PRESETS = {
    "best64": "/usr/share/hashcat/rules/best64.rule",
    "dive": "/usr/share/hashcat/rules/dive.rule",
    "rockyou-30000": "/usr/share/hashcat/rules/rockyou-30000.rule",
    "OneRuleToRuleThemAll": "/usr/share/hashcat/rules/OneRuleToRuleThemAll.rule",
}
BUILTIN_MASKS = {
    "8 цифр": "?d?d?d?d?d?d?d?d",
    "6 цифр": "?d?d?d?d?d?d",
    "8 строчных": "?l?l?l?l?l?l?l?l",
    "cap + 6 цифр": "?u?l?l?l?l?l?d?d",
    "только hex": "?h?h?h?h?h?h?h?h",
}


class Crack:
    def __init__(self, jobs: JobRegistry, workdir: Path):
        self.jobs = jobs
        self.workdir = ensure_dir(workdir)
        self.job: Job | None = None
        self.found: list[str] = []
        self.speed = ""
        self.progress = 0.0
        self.recovered = 0
        self._poller: threading.Thread | None = None
        self._stop = threading.Event()
        self._devices_cache: dict | None = None
        self.keyspace = 0

    # ---------------------------------------------------------------- devices
    def devices(self) -> dict:
        if self._devices_cache:
            return self._devices_cache
        hc = require("hashcat")
        res = run([hc, "-I"], timeout=40)
        text = res.out + res.err
        backends = [ln.strip() for ln in text.splitlines()
                    if ln.startswith(("Backend Device ID", "Type.", "Name.", "Processor"))]
        self._devices_cache = {
            "ok": "Backend Device ID" in text,
            "raw": text[-3000:],
            "summary": backends[:24],
            "hint": None if "Type. : GPU" in text else "только CPU — на большом словаре будет медленно",
        }
        return self._devices_cache

    # ------------------------------------------------------------------- start
    def start(self, hash_file: Path, attack: str, wordlist: Path | None = None,
              rules: str | None = None, mask: str | None = None,
              custom_charset: str | None = None, runtime: int | None = None,
              mask_spec: MaskSpec | None = None) -> dict:
        if self.job and self.job.state in ("starting", "running", "stopping"):
            raise WilfiError("крошилка уже работает", code="busy")
        if not hash_file.is_file() or not hash_file.read_text().strip():
            raise WilfiError("пустой хэш-файл", code="no_hash")
        hc = require("hashcat")
        potfile = self.workdir / "hashcat.potfile"
        outfile = self.workdir / "found.txt"
        argv = [hc, "-m", "22000", str(hash_file), "--potfile-path", str(potfile),
                "-o", str(outfile), "--outfile-format", "2", "--status-json",
                "--status-timer", "2", "--force", "--quiet"]
        if runtime:
            argv += ["--runtime", str(runtime)]
        if custom_charset:
            argv += ["-1", custom_charset]
        if attack == "wordlist":
            if not wordlist or not wordlist.is_file():
                raise WilfiError("словарь не найден", code="no_wordlist")
            argv.append(str(wordlist))
            if rules:
                rule_path = Path(rules) if rules.startswith("/") else Path(RULES_PRESETS.get(rules, rules))
                if rule_path.is_file():
                    argv += ["-r", str(rule_path)]
                elif rules:
                    raise WilfiError(f"правила не найдены: {rules}", code="no_rules")
        elif attack == "positions":
            if not mask_spec:
                raise WilfiError("не собрана маска по позициям", code="no_mask")
            argv += mask_spec.argv_fragment()
            self.keyspace = mask_spec.keyspace
        elif attack == "mask":
            if not mask:
                raise WilfiError("маска пуста", code="no_mask")
            argv += ["-a", "3", mask]
        elif attack == "hybrid":
            if not wordlist or not wordlist.is_file():
                raise WilfiError("словарь не найден", code="no_wordlist")
            suffix = mask or "?d?d"
            argv += ["-a", "6", str(wordlist), suffix]
        elif attack == "combinator":
            if not wordlist:
                raise WilfiError("словарь не найден", code="no_wordlist")
            argv += ["-a", "1", str(wordlist), str(wordlist)]
        else:
            raise WilfiError(f"неизвестная атака {attack}")
        self.found = []
        self.speed = ""
        self.progress = 0.0
        self.recovered = 0
        self.keyspace = 0
        if outfile.exists():
            outfile.unlink()
        job = Job("crack", argv, title=f"hashcat {attack}")
        job.on_exit.append(self._on_exit)
        self.job = job
        self._stop.clear()
        self.jobs.add(job)
        self._poller = threading.Thread(target=self._poll, args=(job,), daemon=True)
        self._poller.start()
        return self.status()

    def _on_exit(self, job: Job) -> None:
        outfile = self.workdir / "found.txt"
        if outfile.exists():
            for line in outfile.read_text(errors="replace").splitlines():
                if ":" in line:
                    psk = line.rsplit(":", 1)[-1].strip()
                    if psk and psk not in self.found:
                        self.found.append(psk)
        if self.found:
            self.recovered = len(self.found)
            self.progress = 100.0

    def _poll(self, job: Job) -> None:
        cursor = job.cursor
        while not self._stop.is_set() and job.state in ("starting", "running", "stopping"):
            newer = job.drain(cursor)
            if newer:
                cursor = newer[-1][0]
            for _, line in newer:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                speed = data.get("speed") or []
                if speed and isinstance(speed[0], (int, float)):
                    self.speed = _human_speed(speed[0])
                prog = data.get("progress") or []
                if prog and isinstance(prog[0], (int, float)):
                    self.progress = round(float(prog[0]), 2)
                self.recovered = data.get("recovered_hashes") or self.recovered
            time.sleep(1.0)

    def stop(self) -> dict:
        self._stop.set()
        if self.job and self.job.state in ("starting", "running", "stopping"):
            self.job.request_stop()
        return self.status()

    def status(self) -> dict:
        return {
            "job": self.job.status() if self.job else None,
            "running": bool(self.job and self.job.state in ("starting", "running", "stopping")),
            "speed": self.speed,
            "progress": self.progress,
            "found": self.found,
            "recovered": self.recovered,
            "keyspace": self.keyspace,
        }


def _human_speed(value: float) -> str:
    for unit in ("H/s", "kH/s", "MH/s", "GH/s"):
        if value < 1000:
            return f"{value:.0f} {unit}" if unit == "H/s" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} TH/s"
