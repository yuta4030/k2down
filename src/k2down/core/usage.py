"""usage.jsonl への利用ログの追記と読み出し。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from k2down.core.model import RuleError

EVENTS = (
    "applied",
    "rejected",
    "decided",
    "escalated",
    "added",
    "replaced",
    "retired",
    "proposed",
    "accepted",
    "declined",
)
PROBLEM_SUMMARY_MAX = 200


class UsageLog:
    """1 行 1 イベントの追記専用ログ。既存行は書き換えない。"""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def append(
        self,
        event: str,
        rule_id: str,
        problem: str,
        ts: datetime | None = None,
        decision: str | None = None,
    ) -> None:
        """ルールを問題に当てた（applied）・人が却下した（rejected）ことを記録する。"""
        self.write(event, ts=ts, rule_id=rule_id, problem=summarize(problem), decision=decision)

    def write(self, event: str, ts: datetime | None = None, **fields: Any) -> None:
        """任意のイベントを 1 行追記する。値が None のフィールドは書かない。"""
        if event not in EVENTS:
            raise ValueError(f"unknown event: {event}")
        ts = ts or datetime.now().astimezone()
        record = {"ts": ts.isoformat(timespec="seconds"), "event": event}
        record.update((key, value) for key, value in fields.items() if value is not None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self) -> list[dict[str, Any]]:
        """全イベントを書かれた順に返す。ファイルがなければ空。"""
        if not self.path.exists():
            return []
        records = []
        with self.path.open(encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    raise RuleError(f"{self.path.name} line {number}: {e}") from None
                if not isinstance(record, dict):
                    raise RuleError(f"{self.path.name} line {number}: not an object")
                records.append(record)
        return records

    def replacements(self) -> dict[str, str]:
        """置き換え前の ID から置き換え後の ID への対応を返す。"""
        return {
            record["rule_id"]: record["replaced_by"]
            for record in self.read()
            if record.get("event") == "replaced" and "rule_id" in record and "replaced_by" in record
        }


def summarize(problem: str) -> str:
    """問題文を 1 行に詰め、長ければ切り詰める。"""
    text = " ".join(problem.split())
    if len(text) > PROBLEM_SUMMARY_MAX:
        text = text[: PROBLEM_SUMMARY_MAX - 1] + "…"
    return text
