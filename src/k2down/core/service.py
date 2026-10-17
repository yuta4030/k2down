"""ルール適用の手続き。"""

from __future__ import annotations

from k2down.core.judge import Judge
from k2down.core.model import Rule, RuleError
from k2down.core.store import RuleStore
from k2down.core.usage import UsageLog


async def find_rules(store: RuleStore, judge: Judge, problem: str, log: UsageLog | None = None) -> list[Rule]:
    """全ルールを走査して problem に当てはまるものを返し、適用ログを残す。

    判定器が存在しない ID を返しても無視する。結果は木の順に並ぶ。
    """
    problem = problem.strip()
    if not problem:
        raise ValueError("problem must not be empty")
    rules = store.rules()
    if not rules:
        return []
    selected = set(await judge.select(problem, rules))
    matched = [rule for rule in rules if rule.id in selected]
    if log is not None:
        for rule in matched:
            log.append("applied", rule.id, problem)
    return matched


def record(store: RuleStore, log: UsageLog, event: str, rule_ids: list[str], problem: str) -> list[Rule]:
    """判定器の外（ホスト側の AI や人間）で下された判定をログに残す。

    存在しない ID が 1 つでもあれば何も書かずに RuleError を送出する。
    """
    problem = problem.strip()
    if not problem:
        raise ValueError("problem must not be empty")
    by_id = {rule.id: rule for rule in store.rules()}
    unknown = [rule_id for rule_id in rule_ids if rule_id not in by_id]
    if unknown:
        raise RuleError(f"unknown rule id: {', '.join(unknown)}")
    rules = [by_id[rule_id] for rule_id in dict.fromkeys(rule_ids)]
    for rule in rules:
        log.append(event, rule.id, problem)
    return rules
