"""rules.json の読み書き。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from k2down.core.model import Node, Rule, RuleError, parse_item, validate_rule_text

FORMAT_VERSION = 1


class RuleStore:
    """rules.json に保存されたルール木。

    ファイルが存在しなければ空の木として扱い、最初の保存時に作成する。
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
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
        text = json.dumps(
            {"version": FORMAT_VERSION, "root": self.root.to_dict()},
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

    def get(self, item_id: str) -> Node | Rule | None:
        for item in _walk(self.root):
            if item.id == item_id:
                return item
        return None

    def add_rule(self, text: str, parent_id: str | None = None) -> Rule:
        """ルールを parent_id（省略時はルート）の子として追加し、保存する。"""
        text = validate_rule_text(text)
        parent = self.root if parent_id is None else self.get(parent_id)
        if not isinstance(parent, Node):
            raise RuleError(f"parent node not found: {parent_id}")
        rule = Rule(id=self._next_id("R"), rule=text)
        parent.children.append(rule)
        self.save()
        return rule

    def _next_id(self, prefix: str) -> str:
        numbers = [int(item.id[1:]) for item in _walk(self.root) if item.id.startswith(prefix)]
        return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _walk(node: Node) -> Iterator[Node | Rule]:
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from _walk(child)
        else:
            yield child
