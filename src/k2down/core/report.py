"""usage.jsonl を数えて、ルールの手入れの候補を出す。

数えるだけで、意味の判定（本当に逆を指すか、似ているか）はしない。それはホスト側が行う。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from itertools import combinations
from typing import Any

from k2down.core.model import Proposal, Rule

COUNTS = ("applied", "hit", "miss", "rejected")
PROPOSAL_EVENTS = ("proposed", "accepted", "declined")
MIN_DECISIONS = 10


def build_report(
    rules: list[Rule],
    records: list[dict[str, Any]],
    since: date | None = None,
    pending: list[Proposal] | None = None,
    min_decisions: int = MIN_DECISIONS,
) -> dict[str, Any]:
    """現在のルールとログから集計結果を返す。since を渡すとその日以降のイベントだけを数える。

    落とす候補は、足してから（足した記録がなければ期間の初めから）min_decisions 件以上の判断が
    記録されたのに一度も当たっていないルール。足したばかりのルールは候補に入らない。
    """
    if min_decisions < 0:
        raise ValueError(f"min_decisions must not be negative: {min_decisions}")
    # 提案の中身は期間より前に出されたこともあるので、全期間の記録から引く。
    proposed = {r["proposal"]: r for r in records if r.get("event") == "proposed" and "proposal" in r}
    if since is not None:
        records = [r for r in records if _day(r) is not None and _day(r) >= since.isoformat()]

    # 同じ決断 ID の記録をまとめる。答え合わせは最後の decided を正とする（追記で訂正できるように）。
    applied_in: dict[str, list[str]] = defaultdict(list)
    problems: dict[str, str] = {}
    decided: dict[str, dict[str, Any]] = {}
    escalated: dict[str, dict[str, Any]] = {}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    added_at: dict[str, datetime | None] = {}
    proposal_counts: Counter[str] = Counter()
    declined: list[dict[str, Any]] = []
    for record in records:
        event, decision, rule_id = record.get("event"), record.get("decision"), record.get("rule_id")
        if event == "added" and rule_id:
            added_at[rule_id] = _time(record)
        elif event == "replaced" and record.get("replaced_by"):
            added_at[record["replaced_by"]] = _time(record)
        elif event in PROPOSAL_EVENTS and record.get("proposal"):
            proposal_counts[event] += 1
            if event == "declined":
                content = {k: v for k, v in proposed.get(record["proposal"], {}).items() if k not in ("ts", "event")}
                declined.append({**content, "proposal": record["proposal"], "reason": record.get("reason")})
        if decision and record.get("problem"):
            problems.setdefault(decision, record["problem"])
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

    decided_times = [_time(record) for record in decided.values()]

    def decisions_since(rule_id: str) -> int:
        start = added_at.get(rule_id)
        if start is None:
            return len(decided_times)
        return sum(1 for t in decided_times if t is not None and t >= start)

    current = {rule.id for rule in rules}
    rule_rows = [
        {
            "id": rule.id,
            "rule": rule.rule,
            **{key: counts[rule.id][key] for key in COUNTS},
            "decisions": decisions_since(rule.id),
        }
        for rule in rules
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
        "min_decisions": min_decisions,
        "drop_candidates": [
            row["id"] for row in rule_rows if row["applied"] == 0 and row["decisions"] >= min_decisions
        ],
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
                "proposals": [pid for pid, p in proposed.items() if p.get("decision") == decision],
            }
            for decision, record in decided.items()
            if record.get("outcome") == "none"
        ],
        "proposals": {
            **{event: proposal_counts[event] for event in PROPOSAL_EVENTS},
            "pending": len(pending or []),
        },
        "declined_proposals": declined,
        "daily": [
            {"date": day, "decided": c["decided"], "hit": c["hit"], "ratio": round(c["hit"] / c["decided"], 2)}
            for day, c in sorted(days.items())
        ],
    }


def _time(record: dict[str, Any]) -> datetime | None:
    """記録時刻。タイムゾーンの違う記録どうしも比べられるよう datetime にする。"""
    try:
        t = datetime.fromisoformat(record["ts"])
    except (KeyError, TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else t.astimezone()


def _day(record: dict[str, Any]) -> str | None:
    """記録時刻の日付（記録したときのタイムゾーンでの日付）。"""
    ts = record.get("ts")
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None
