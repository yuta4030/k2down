"""ルール木のデータ構造。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

RULE_ID = re.compile(r"^R\d{3,}$")
NODE_ID = re.compile(r"^N\d{3,}$")


class RuleError(ValueError):
    """ルールやルール木が不正なときに送出する。"""


@dataclass
class Rule:
    """葉。自然言語 1 行のルール。"""

    id: str
    rule: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "rule": self.rule}
        if self.note is not None:
            data["note"] = self.note
        return data


@dataclass
class Node:
    """内部ノード。summary は子の要約。"""

    id: str
    summary: str
    children: list[Node | Rule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "children": [child.to_dict() for child in self.children],
        }


def validate_rule_text(text: str) -> str:
    """ルール文を検証し、前後の空白を除いて返す。"""
    if not isinstance(text, str):
        raise RuleError("rule must be a string")
    text = text.strip()
    if not text:
        raise RuleError("rule must not be empty")
    if "\n" in text or "\r" in text:
        raise RuleError("rule must be a single line")
    return text


def parse_item(data: Any) -> Node | Rule:
    if not isinstance(data, dict):
        raise RuleError(f"tree item must be an object: {data!r}")
    item_id = data.get("id")
    if not isinstance(item_id, str):
        raise RuleError(f"tree item has no id: {data!r}")
    if "children" in data:
        if not NODE_ID.match(item_id):
            raise RuleError(f"invalid node id: {item_id}")
        children = data["children"]
        if not isinstance(children, list):
            raise RuleError(f"children of {item_id} must be a list")
        return Node(
            id=item_id,
            summary=str(data.get("summary", "")),
            children=[parse_item(child) for child in children],
        )
    if "rule" in data:
        if not RULE_ID.match(item_id):
            raise RuleError(f"invalid rule id: {item_id}")
        note = data.get("note")
        if note is not None and not isinstance(note, str):
            raise RuleError(f"note of {item_id} must be a string")
        return Rule(id=item_id, rule=validate_rule_text(data["rule"]), note=note)
    raise RuleError(f"tree item {item_id} has neither children nor rule")
