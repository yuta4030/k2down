"""ルールと提案のデータ構造。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

RULE_ID = re.compile(r"^R\d{3,}$")
PROPOSAL_ID = re.compile(r"^P\d{3,}$")
PROPOSAL_KINDS = ("add", "retire", "replace")


class RuleError(ValueError):
    """ルールや提案が不正なときに送出する。"""


@dataclass
class Rule:
    """自然言語 1 行のルール。scopes が空なら全体共通。"""

    id: str
    rule: str
    scopes: list[str] = field(default_factory=list)
    decision: str | None = None
    source: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "rule": self.rule}
        if self.scopes:
            data["scopes"] = list(self.scopes)
        for key in ("decision", "source", "note"):
            if getattr(self, key) is not None:
                data[key] = getattr(self, key)
        return data


@dataclass
class Proposal:
    """ルールを足す・外す・置き換える提案。人が受け入れるまでルールにはならない。

    add は rule、retire は rule_id、replace は両方を持つ。
    """

    id: str
    kind: str
    rule: str | None = None
    rule_id: str | None = None
    scopes: list[str] = field(default_factory=list)
    decision: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "kind": self.kind}
        for key in ("rule", "rule_id", "decision", "source"):
            if getattr(self, key) is not None:
                data[key] = getattr(self, key)
        if self.scopes:
            data["scopes"] = list(self.scopes)
        return data

    def same_content(self, other: Proposal) -> bool:
        """中身（種類・対象・文言・範囲）が同じか。出どころは比べない。"""
        return (self.kind, self.rule_id, self.rule, self.scopes) == (other.kind, other.rule_id, other.rule, other.scopes)


def validate_rule_text(text: str) -> str:
    """ルール文を検証し、前後の空白を除いて返す。"""
    return validate_line(text, "rule")


def validate_line(text: str, name: str) -> str:
    """空でない 1 行の文字列かを検証し、前後の空白を除いて返す。"""
    if not isinstance(text, str):
        raise RuleError(f"{name} must be a string")
    text = text.strip()
    if not text:
        raise RuleError(f"{name} must not be empty")
    if "\n" in text or "\r" in text:
        raise RuleError(f"{name} must be a single line")
    return text


def validate_token(value: str, name: str) -> str:
    """決断 ID や範囲の名前は、空白を含まない空でない文字列。"""
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise RuleError(f"{name} must be non-empty and contain no whitespace: {value!r}")
    return value


def normalize_scopes(scopes: Any) -> list[str]:
    """範囲の名前を検証し、重複を除いて名前順に並べる。"""
    if scopes is None:
        return []
    if not isinstance(scopes, list):
        raise RuleError(f"scopes must be a list: {scopes!r}")
    return sorted({validate_token(scope, "scope") for scope in scopes})


def optional_line(value: Any, name: str) -> str | None:
    return None if value is None else validate_line(value, name)


def optional_token(value: Any, name: str) -> str | None:
    return None if value is None else validate_token(value, name)


def parse_rule(data: Any) -> Rule:
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise RuleError(f"rule has no id: {data!r}")
    rule_id = data["id"]
    if not RULE_ID.match(rule_id):
        raise RuleError(f"invalid rule id: {rule_id}")
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise RuleError(f"note of {rule_id} must be a string")
    return Rule(
        id=rule_id,
        rule=validate_rule_text(data.get("rule")),
        scopes=normalize_scopes(data.get("scopes")),
        decision=optional_token(data.get("decision"), "decision"),
        source=optional_line(data.get("source"), "source"),
        note=note,
    )


def parse_proposal(data: Any) -> Proposal:
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise RuleError(f"proposal has no id: {data!r}")
    proposal_id = data["id"]
    if not PROPOSAL_ID.match(proposal_id):
        raise RuleError(f"invalid proposal id: {proposal_id}")
    return new_proposal(
        data.get("kind"),
        rule=data.get("rule"),
        rule_id=data.get("rule_id"),
        scopes=data.get("scopes"),
        decision=data.get("decision"),
        source=data.get("source"),
        proposal_id=proposal_id,
    )


def new_proposal(
    kind: Any,
    rule: Any = None,
    rule_id: Any = None,
    scopes: Any = None,
    decision: Any = None,
    source: Any = None,
    proposal_id: str = "",
) -> Proposal:
    """種類に合った項目がそろっているかを検証して提案を作る。"""
    if kind not in PROPOSAL_KINDS:
        raise RuleError(f"proposal kind must be one of {', '.join(PROPOSAL_KINDS)}: {kind!r}")
    needs_rule, needs_target = kind in ("add", "replace"), kind in ("retire", "replace")
    if needs_rule == (rule is None):
        raise RuleError(f"{kind} proposal {'needs' if needs_rule else 'takes no'} rule text")
    if needs_target == (rule_id is None):
        raise RuleError(f"{kind} proposal {'needs' if needs_target else 'takes no'} target rule id")
    if rule_id is not None and (not isinstance(rule_id, str) or not RULE_ID.match(rule_id)):
        raise RuleError(f"invalid rule id: {rule_id!r}")
    if kind == "retire" and scopes:
        raise RuleError("retire proposal takes no scopes")
    return Proposal(
        id=proposal_id,
        kind=kind,
        rule=None if rule is None else validate_rule_text(rule),
        rule_id=rule_id,
        scopes=normalize_scopes(scopes),
        decision=optional_token(decision, "decision"),
        source=optional_line(source, "source"),
    )
