"""store のディレクトリの簡易ロック。

複数のエージェントが同時に k2down を呼んでも、読む → 変える → 書く が混ざらないようにする。
ロックファイルを「すでにあれば失敗する」モードで作るだけなので、OS ごとの違いがない。
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from k2down.core.model import RuleError

LOCK_FILE = ".k2down.lock"
TIMEOUT = 10.0
# k2down のコマンドは一瞬で終わる。これより古いロックは、落ちたプロセスが残したものとみなす。
STALE_AFTER = 30.0
POLL = 0.05


class LockError(RuleError):
    """ロックを取れなかったときに送出する。"""


@contextmanager
def locked(
    directory: str | os.PathLike[str],
    timeout: float | None = None,
    stale_after: float | None = None,
) -> Iterator[None]:
    """directory のロックを取ってから中の処理を行い、終わったら外す。取れなければ timeout 秒で LockError。"""
    timeout = TIMEOUT if timeout is None else timeout
    stale_after = STALE_AFTER if stale_after is None else stale_after
    path = Path(directory) / LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _is_stale(path, stale_after):
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise LockError(f"store is locked by another k2down process: {path}") from None
            time.sleep(POLL)
            continue
        break
    try:
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()}\n")
        yield
    finally:
        path.unlink(missing_ok=True)


def _is_stale(path: Path, stale_after: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime > stale_after
    except FileNotFoundError:
        return False
