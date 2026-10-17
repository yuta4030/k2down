"""ルール適用と記録の手続き。"""

from __future__ import annotations

from k2down.core.judge import Judge
from k2down.core.model import Rule, RuleError
from k2down.core.store import RuleStore
from k2down.core.usage import UsageLog, summarize

OUTCOMES = ("hit", "miss", "none")
REASONS = ("no_match", "conflict")


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


def record(
    store: RuleStore,
    log: UsageLog,
    event: str,
    rule_ids: list[str],
    problem: str,
    decision: str | None = None,
) -> list[Rule]:
    """判定器の外（ホスト側の AI や人間）で下された判定をログに残す。

    存在しない ID が 1 つでもあれば何も書かずに RuleError を送出する。
    """
    problem = require_text(problem, "problem")
    if decision is not None:
        decision = validate_decision(decision)
    rules = lookup_rules(store, log, rule_ids)
    for rule in rules:
        log.append(event, rule.id, problem, decision=decision)
    return rules


def decide(
    log: UsageLog,
    decision: str,
    actual: str,
    outcome: str,
    predicted: str | None = None,
    problem: str | None = None,
) -> dict[str, str]:
    """ルールからの予測と人の決断の答え合わせを記録する。一致したかどうかは呼び出し側が判定して渡す。"""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}: {outcome}")
    fields = {
        "decision": validate_decision(decision),
        "problem": None if problem is None else require_text(problem, "problem"),
        "predicted": None if predicted is None else require_text(predicted, "predicted"),
        "actual": require_text(actual, "actual"),
        "outcome": outcome,
    }
    fields = {key: value for key, value in fields.items() if value is not None}
    log.write("decided", **fields)
    return fields


def escalate(
    store: RuleStore,
    log: UsageLog,
    decision: str,
    problem: str,
    reason: str,
    rule_ids: list[str] | None = None,
) -> list[Rule]:
    """ルールで決まらず人に聞いたことを記録する。conflict のときはぶつかったルールを 2 つ以上渡す。"""
    decision = validate_decision(decision)
    problem = require_text(problem, "problem")
    rule_ids = rule_ids or []
    if reason not in REASONS:
        raise ValueError(f"reason must be one of {', '.join(REASONS)}: {reason}")
    if reason == "conflict" and len(set(rule_ids)) < 2:
        raise ValueError("conflict needs at least two rule ids")
    if reason == "no_match" and rule_ids:
        raise ValueError("no_match takes no rule ids")
    rules = lookup_rules(store, log, rule_ids)
    log.write(
        "escalated",
        decision=decision,
        problem=problem,
        reason=reason,
        rule_ids=[rule.id for rule in rules] or None,
    )
    return rules


def replace(store: RuleStore, log: UsageLog, old_id: str, text: str, source: str | None = None) -> tuple[Rule, Rule]:
    """ルールを新しい ID のルールに置き換え、旧 ID から新 ID への対応をログに残す。"""
    old, new = store.replace_rule(old_id, text, source)
    log.write("replaced", rule_id=old.id, replaced_by=new.id)
    return old, new


def retire(store: RuleStore, log: UsageLog, rule_ids: list[str]) -> list[Rule]:
    """ルールを消し、ログに残す。"""
    rules = store.retire_rules(rule_ids)
    for rule in rules:
        log.write("retired", rule_id=rule.id)
    return rules


def lookup_rules(store: RuleStore, log: UsageLog, rule_ids: list[str]) -> list[Rule]:
    """ID のルールを重複なしで返す。置き換え済みの ID には置き換え先を添えてエラーにする。"""
    by_id = {rule.id: rule for rule in store.rules()}
    unknown = [rule_id for rule_id in rule_ids if rule_id not in by_id]
    if unknown:
        replaced = log.replacements()
        described = [f"{rule_id} (replaced by {replaced[rule_id]})" if rule_id in replaced else rule_id for rule_id in unknown]
        raise RuleError(f"unknown rule id: {', '.join(described)}")
    return [by_id[rule_id] for rule_id in dict.fromkeys(rule_ids)]


def validate_decision(decision: str) -> str:
    """決断 ID は空白を含まない空でない文字列。"""
    if not decision or any(c.isspace() for c in decision):
        raise ValueError(f"decision id must be non-empty and contain no whitespace: {decision!r}")
    return decision


def require_text(text: str, name: str) -> str:
    """空でない文を 1 行に詰めて返す。"""
    text = summarize(text)
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text
