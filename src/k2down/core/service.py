"""ルール適用と記録の手続き。"""

from __future__ import annotations

from k2down.core.judge import Judge
from k2down.core.model import Proposal, Rule, RuleError, new_proposal
from k2down.core.store import ProposalStore, RuleStore
from k2down.core.usage import UsageLog, summarize

OUTCOMES = ("hit", "miss", "none")
REASONS = ("no_match", "conflict")


async def find_rules(
    store: RuleStore,
    judge: Judge,
    problem: str,
    log: UsageLog | None = None,
    scopes: list[str] | None = None,
) -> list[Rule]:
    """ルールを走査して problem に当てはまるものを返し、適用ログを残す。

    scopes を渡すと、その範囲と全体共通のルールだけを見る。
    判定器が存在しない ID を返しても無視する。結果はルールの並び順に並ぶ。
    """
    problem = problem.strip()
    if not problem:
        raise ValueError("problem must not be empty")
    rules = store.rules(scopes)
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


def add(
    store: RuleStore,
    log: UsageLog,
    text: str,
    scopes: list[str] | None = None,
    decision: str | None = None,
    source: str | None = None,
    proposal: str | None = None,
) -> Rule:
    """ルールを足し、足したことをログに残す（report が足してからの判断の数を数えるのに使う）。"""
    if decision is not None:
        decision = validate_decision(decision)
    rule = store.add_rule(text, scopes, decision, source)
    log.write("added", rule_id=rule.id, decision=decision, proposal=proposal)
    return rule


def replace(
    store: RuleStore,
    log: UsageLog,
    old_id: str,
    text: str,
    scopes: list[str] | None = None,
    decision: str | None = None,
    source: str | None = None,
    proposal: str | None = None,
) -> tuple[Rule, Rule]:
    """ルールを新しい ID のルールに置き換え、旧 ID から新 ID への対応をログに残す。scopes を省くと引き継ぐ。"""
    if decision is not None:
        decision = validate_decision(decision)
    lookup_rules(store, log, [old_id])
    old, new = store.replace_rule(old_id, text, scopes, decision, source)
    log.write("replaced", rule_id=old.id, replaced_by=new.id, decision=decision, proposal=proposal)
    return old, new


def retire(store: RuleStore, log: UsageLog, rule_ids: list[str], proposal: str | None = None) -> list[Rule]:
    """ルールを消し、ログに残す。"""
    lookup_rules(store, log, rule_ids)
    rules = store.retire_rules(rule_ids)
    for rule in rules:
        log.write("retired", rule_id=rule.id, proposal=proposal)
    return rules


def propose(
    store: RuleStore,
    proposals: ProposalStore,
    log: UsageLog,
    kind: str,
    rule: str | None = None,
    rule_id: str | None = None,
    scopes: list[str] | None = None,
    decision: str | None = None,
    source: str | None = None,
) -> tuple[Proposal, bool]:
    """提案を出す。(提案, 新しく出したか) を返す。

    中身（種類・対象・文言・範囲）が同じ提案が残っていれば、新しく振らずにそれを返す。再送しても増えない。
    """
    if decision is not None:
        decision = validate_decision(decision)
    proposal = new_proposal(kind, rule=rule, rule_id=rule_id, scopes=scopes, decision=decision, source=source)
    if proposal.rule_id is not None:
        lookup_rules(store, log, [proposal.rule_id])
    same = proposals.find_same(proposal)
    if same is not None:
        return same, False
    proposals.add(proposal)
    data = proposal.to_dict()
    log.write("proposed", proposal=data.pop("id"), **data)
    return proposal, True


def accept(store: RuleStore, proposals: ProposalStore, log: UsageLog, proposal_ids: list[str]) -> list[dict[str, str]]:
    """提案を受け入れてルールに反映する。提案ごとに、反映した結果を返す。

    1 つでも受け入れられない提案があれば、何も変えずにエラーにする。
    """
    pending = lookup_proposals(proposals, log, proposal_ids)
    targets = [p.rule_id for p in pending if p.rule_id is not None]
    if len(targets) != len(set(targets)):
        raise RuleError(f"several proposals target the same rule: {', '.join(sorted(targets))}")
    lookup_rules(store, log, targets)

    results = []
    for p in pending:
        log.write("accepted", proposal=p.id)
        result = {"proposal": p.id, "kind": p.kind}
        if p.kind == "add":
            assert p.rule is not None
            result["rule_id"] = add(store, log, p.rule, p.scopes, p.decision, p.source, proposal=p.id).id
        elif p.kind == "retire":
            assert p.rule_id is not None
            result["rule_id"] = retire(store, log, [p.rule_id], proposal=p.id)[0].id
        else:
            assert p.rule is not None and p.rule_id is not None
            scopes = p.scopes or None  # 範囲のない置き換えの提案は、古いルールの範囲を引き継ぐ
            old, new = replace(store, log, p.rule_id, p.rule, scopes, p.decision, p.source, proposal=p.id)
            result.update(rule_id=old.id, replaced_by=new.id)
        results.append(result)
    proposals.remove([p.id for p in pending])
    return results


def decline(proposals: ProposalStore, log: UsageLog, proposal_ids: list[str], reason: str | None = None) -> list[Proposal]:
    """提案を却下する。却下したことと理由はログに残り、report で見られる。"""
    pending = lookup_proposals(proposals, log, proposal_ids)
    reason = None if reason is None else require_text(reason, "reason")
    for p in pending:
        log.write("declined", proposal=p.id, reason=reason)
    proposals.remove([p.id for p in pending])
    return pending


def lookup_proposals(proposals: ProposalStore, log: UsageLog, proposal_ids: list[str]) -> list[Proposal]:
    """ID の提案を重複なしで返す。決まった提案にはどう決まったかを添えてエラーにする。"""
    unknown = [proposal_id for proposal_id in proposal_ids if proposals.get(proposal_id) is None]
    if unknown:
        settled = {
            record["proposal"]: record["event"]
            for record in log.read()
            if record.get("event") in ("accepted", "declined") and "proposal" in record
        }
        described = [f"{pid} (already {settled[pid]})" if pid in settled else pid for pid in unknown]
        raise RuleError(f"unknown proposal id: {', '.join(described)}")
    found = [proposals.get(proposal_id) for proposal_id in dict.fromkeys(proposal_ids)]
    return [p for p in found if p is not None]


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
