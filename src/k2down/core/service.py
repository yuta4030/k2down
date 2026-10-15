"""ルール適用の手続き。"""

from __future__ import annotations

from k2down.core.judge import Judge
from k2down.core.model import Rule
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
