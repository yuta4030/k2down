import json
import os
import subprocess
import sys
import time

import pytest

from k2down.cli import main
from k2down.core import LockError, locked
from k2down.core.lock import LOCK_FILE


def test_lock_file_exists_only_while_held(tmp_path):
    with locked(tmp_path):
        assert (tmp_path / LOCK_FILE).exists()
    assert not (tmp_path / LOCK_FILE).exists()


def test_lock_is_released_on_error(tmp_path):
    with pytest.raises(ValueError):
        with locked(tmp_path):
            raise ValueError("boom")
    assert not (tmp_path / LOCK_FILE).exists()


def test_held_lock_times_out(tmp_path):
    with locked(tmp_path):
        with pytest.raises(LockError):
            with locked(tmp_path, timeout=0.1):
                pass


def test_stale_lock_is_taken_over(tmp_path):
    (tmp_path / LOCK_FILE).write_text("12345\n")
    old = time.time() - 60
    os.utime(tmp_path / LOCK_FILE, (old, old))
    with locked(tmp_path, timeout=0.1):
        pass


def test_cli_reports_lock_as_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("k2down.core.lock.TIMEOUT", 0.1)
    (tmp_path / LOCK_FILE).write_text("12345\n")
    assert main(["--dir", str(tmp_path), "add", "a"]) == 1
    assert "locked" in capsys.readouterr().err
    assert not (tmp_path / "rules.json").exists()
    assert main(["--dir", str(tmp_path), "list"]) == 0  # 読むだけのコマンドはロックを待たない


def test_parallel_processes_do_not_lose_writes(tmp_path):
    """複数のプロセスが同時に提案を出しても、どれも消えず、ID もぶつからない。"""
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "k2down", "--dir", str(tmp_path), "propose", "add", f"rule {n}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n in range(12)
    ]
    outputs = [p.communicate(timeout=60) for p in procs]
    assert [p.returncode for p in procs] == [0] * 12, outputs
    ids = {out.strip() for out, _ in outputs}
    assert len(ids) == 12
    saved = json.loads((tmp_path / "proposals.json").read_text(encoding="utf-8"))
    assert {p["id"] for p in saved["proposals"]} == ids
    assert not (tmp_path / LOCK_FILE).exists()
