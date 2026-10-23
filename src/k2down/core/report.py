"""usage.jsonl を数えて、ルールの手入れの候補を出す。

数えるだけで、意味の判定（本当に逆を指すか、似ているか）はしない。それはホスト側が行う。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from typing import Any

from k2down.core.model import Rule

COUNTS = ("applied", "hit", "miss", "rejected")
# 本文に書かれたルール ID（「R003 を R017 より優先する」など）。日本語に続いても拾えるよう英数字の境目で切る。
RULE_REF = re.compile(r"(?<![A-Za-z0-9])R\d{3,}(?![0-9])")


def build_report(rules: list[Rule], records: list[dict[str, Any]], since: date | None = None) -> dict[str, Any]:
    """現在のルールとログから集計結果を返す。since を渡すとその日以降のイベントだけを数える。"""
    # 置き換えの対応は期間に関係なくたどれるよう、絞り込む前に引いておく。
    replaced_by = {
        r["rule_id"]: r["replaced_by"] for r in records if r.get("event") == "replaced" and "rule_id" in r and "replaced_by" in r
    }
    if since is not None:
        records = [r for r in records if _day(r) is not None and _day(r) >= since.isoformat()]

    # 同じ決断 ID の記録をまとめる。答え合わせは最後の decided を正とする（追記で訂正できるように）。
    applied_in: dict[str, list[str]] = defaultdict(list)
    problems: dict[str, str] = {}
    decided: dict[str, dict[str, Any]] = {}
    escalated: dict[str, dict[str, Any]] = {}
    irreversible: list[str] = []
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        event, decision, rule_id = record.get("event"), record.get("decision"), record.get("rule_id")
        if decision and record.get("problem"):
            problems.setdefault(decision, record["problem"])
        if decision and record.get("irreversible") and decision not in irreversible:
            irreversible.append(decision)
        if event in ("applied", "rejected") and rule_id:
            counts[rule_id][event] += 1
            if event == "applied" and decision and rule_id not in applied_in[decision]:
                applied_in[decision].append(rule_id)
        elif event == "decided" and decision:
            decided[decision] = record
        elif event == "escalated" and decision:
            escalated[decision] = record

    for decision, record in decided.items():
        if record.get("outcome") in ("hit", "miss"):
            for rule_id in applied_in.get(decision, []):
                counts[rule_id][record["outcome"]] += 1

    current = {rule.id for rule in rules}
    rule_rows = [
        {"id": rule.id, "rule": rule.rule, **{key: counts[rule.id][key] for key in COUNTS}} for rule in rules
    ]

    # ぶつかる組：同じ決断で同時に当たって外れた組と、conflict で人に聞いた組。
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for decision, record in decided.items():
        if record.get("outcome") == "miss":
            for pair in combinations(sorted(applied_in.get(decision, [])), 2):
                pairs[pair].append(decision)
    for decision, record in escalated.items():
        if record.get("reason") == "conflict":
            for pair in combinations(sorted(set(record.get("rule_ids", []))), 2):
                if decision not in pairs[pair]:
                    pairs[pair].append(decision)
    conflicts = [
        {"rule_ids": list(pair), "decisions": decisions}
        for pair, decisions in sorted(pairs.items(), key=lambda item: (-len(item[1]), item[0]))
        if set(pair) <= current
    ]

    days: dict[str, Counter[str]] = defaultdict(Counter)
    for record in decided.values():
        day = _day(record)
        if day is not None:
            days[day]["decided"] += 1
            days[day][record.get("outcome", "")] += 1

    return {
        "since": None if since is None else since.isoformat(),
        "decisions": {
            "decided": len(decided),
            **{key: sum(1 for r in decided.values() if r.get("outcome") == key) for key in ("hit", "miss", "none")},
        },
        "rules": rule_rows,
        "drop_candidates": [row["id"] for row in rule_rows if row["applied"] == 0],
        "rewrite_candidates": [
            row["id"]
            for row in sorted(rule_rows, key=lambda row: -(row["miss"] + row["rejected"]))
            if row["miss"] + row["rejected"] > 0
        ],
        "conflict_candidates": conflicts,
        "new_rule_candidates": [
            {
                "decision": decision,
                "problem": problems.get(decision),
                "actual": record.get("actual"),
                "rationale": record.get("rationale"),
            }
            for decision, record in decided.items()
            if record.get("outcome") == "none"
        ],
        "irreversible_decisions": [
            {"decision": decision, "problem": problems.get(decision), "outcome": decided.get(decision, {}).get("outcome")}
            for decision in irreversible
        ],
        "stale_references": _stale_references(rules, current, replaced_by),
        "daily": [
            {"date": day, "decided": c["decided"], "hit": c["hit"], "ratio": round(c["hit"] / c["decided"], 2)}
            for day, c in sorted(days.items())
        ],
    }


def _stale_references(rules: list[Rule], current: set[str], replaced_by: dict[str, str]) -> list[dict[str, Any]]:
    """本文に書かれた ID のうち、もう無いものを返す。置き換え済みなら最後の置き換え先を添える。"""
    stale = []
    for rule in rules:
        refs = []
        for ref in dict.fromkeys(RULE_REF.findall(rule.rule)):
            if ref in current:
                continue
            target, seen = ref, {ref}
            while target in replaced_by and replaced_by[target] not in seen:
                target = replaced_by[target]
                seen.add(target)
            refs.append({"id": ref, "replaced_by": None if target == ref else target})
        if refs:
            stale.append({"id": rule.id, "rule": rule.rule, "refs": refs})
    return stale


def _day(record: dict[str, Any]) -> str | None:
    """記録時刻の日付（記録したときのタイムゾーンでの日付）。"""
    ts = record.get("ts")
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None
