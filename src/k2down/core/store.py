"""rules.json の読み書き。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from k2down.core.model import Node, Rule, RuleError, parse_item, validate_line, validate_rule_text

FORMAT_VERSION = 1
ID_PREFIXES = ("N", "R")


class RuleStore:
    """rules.json に保存されたルール木。

    ファイルが存在しなければ空の木として扱い、最初の保存時に作成する。
    issued は接頭辞ごとの発行済み最大番号。消した ID を再発行しないために持つ。
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.issued: dict[str, int] = {}
        self.root = self._load()

    def _load(self) -> Node:
        if not self.path.exists():
            return Node(id="N000", summary="全体")
        with self.path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise RuleError("rules.json must be an object")
        if data.get("version") != FORMAT_VERSION:
            raise RuleError(f"unsupported rules.json version: {data.get('version')!r}")
        issued = data.get("issued", {})
        if not isinstance(issued, dict) or not all(
            key in ID_PREFIXES and type(value) is int and value >= 0 for key, value in issued.items()
        ):
            raise RuleError(f"invalid issued: {issued!r}")
        self.issued = dict(issued)
        root = parse_item(data.get("root"))
        if not isinstance(root, Node):
            raise RuleError("root must be a node")
        seen: set[str] = set()
        for item in _walk(root):
            if item.id in seen:
                raise RuleError(f"duplicate id: {item.id}")
            seen.add(item.id)
        return root

    def save(self) -> None:
        """キー順・2 スペースインデント・末尾改行を固定して書き出す。"""
        data = {"version": FORMAT_VERSION, "root": self.root.to_dict()}
        if self.issued:
            data["issued"] = self.issued
        text = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".rules.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise

    def rules(self) -> list[Rule]:
        """全ての葉を木の順で返す。"""
        return [item for item in _walk(self.root) if isinstance(item, Rule)]

    def rules_with_parent(self) -> list[tuple[str, Rule]]:
        """全ての葉を (親ノード ID, ルール) の組で木の順に返す。"""
        return list(_walk_rules(self.root))

    def get(self, item_id: str) -> Node | Rule | None:
        for item in _walk(self.root):
            if item.id == item_id:
                return item
        return None

    def add_rule(self, text: str, parent_id: str | None = None, source: str | None = None) -> Rule:
        """ルールを parent_id（省略時はルート）の子として追加し、保存する。"""
        rule = self._new_rule(text, source)
        parent = self.root if parent_id is None else self.get(parent_id)
        if not isinstance(parent, Node):
            raise RuleError(f"parent node not found: {parent_id}")
        self._issue(rule)
        parent.children.append(rule)
        self.save()
        return rule

    def replace_rule(self, old_id: str, text: str, source: str | None = None) -> tuple[Rule, Rule]:
        """old_id のルールを新しい ID のルールに置き換え、保存する。(古いルール, 新しいルール) を返す。

        新しいルールは古いルールと同じ位置に入る。文言の修正ではなく置き換えなので、ID は引き継がない。
        """
        rule = self._new_rule(text, source)
        parent, index = self._locate(old_id)
        self._issue(rule)
        old = parent.children[index]
        parent.children[index] = rule
        self.save()
        return old, rule

    def retire_rules(self, rule_ids: list[str]) -> list[Rule]:
        """ルールを消して保存する。存在しない ID が 1 つでもあれば何も消さずに RuleError を送出する。"""
        rule_ids = list(dict.fromkeys(rule_ids))
        unknown = [rule_id for rule_id in rule_ids if not isinstance(self.get(rule_id), Rule)]
        if unknown:
            raise RuleError(f"unknown rule id: {', '.join(unknown)}")
        self._remember_issued()
        retired = []
        for rule_id in rule_ids:
            parent, index = self._locate(rule_id)
            retired.append(parent.children.pop(index))
        self.save()
        return retired

    def _new_rule(self, text: str, source: str | None) -> Rule:
        text = validate_rule_text(text)
        if source is not None:
            source = validate_line(source, "source")
        return Rule(id="", rule=text, source=source)

    def _locate(self, rule_id: str) -> tuple[Node, int]:
        for parent, rule in _walk_rules(self.root):
            if rule.id == rule_id:
                node = self.get(parent)
                assert isinstance(node, Node)
                return node, node.children.index(rule)
        raise RuleError(f"unknown rule id: {rule_id}")

    def _issue(self, rule: Rule) -> None:
        """新しい ID を発行して rule に付ける。発行済みの番号は二度と使わない。"""
        self._remember_issued()
        self.issued["R"] += 1
        rule.id = f"R{self.issued['R']:03d}"

    def _remember_issued(self) -> None:
        """木に今ある ID の最大番号を issued に反映する（issued を持たない v0.1 のファイル向け）。"""
        for prefix in ID_PREFIXES:
            numbers = [int(item.id[1:]) for item in _walk(self.root) if item.id.startswith(prefix)]
            self.issued[prefix] = max([self.issued.get(prefix, 0), *numbers])


def _walk(node: Node) -> Iterator[Node | Rule]:
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from _walk(child)
        else:
            yield child


def _walk_rules(node: Node) -> Iterator[tuple[str, Rule]]:
    for child in node.children:
        if isinstance(child, Node):
            yield from _walk_rules(child)
        else:
            yield node.id, child
