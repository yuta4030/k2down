"""usage.jsonl への利用ログの追記。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

EVENTS = ("applied", "rejected")
PROBLEM_SUMMARY_MAX = 200


class UsageLog:
    """1 行 1 イベントの追記専用ログ。既存行は書き換えない。"""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def append(self, event: str, rule_id: str, problem: str, ts: datetime | None = None) -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown event: {event}")
        ts = ts or datetime.now().astimezone()
        record = {
            "ts": ts.isoformat(timespec="seconds"),
            "event": event,
            "rule_id": rule_id,
            "problem": summarize(problem),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize(problem: str) -> str:
    """問題文を 1 行に詰め、長ければ切り詰める。"""
    text = " ".join(problem.split())
    if len(text) > PROBLEM_SUMMARY_MAX:
        text = text[: PROBLEM_SUMMARY_MAX - 1] + "…"
    return text
