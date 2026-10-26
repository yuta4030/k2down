"""rules.json と proposals.json の読み書き。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import Any

from k2down.core.model import (
    Proposal,
    Rule,
    RuleError,
    new_id,
    normalize_scopes,
    optional_line,
    optional_token,
    parse_proposal,
    parse_rule,
    validate_rule_text,
)

FORMAT_VERSION = 2
PROPOSALS_VERSION = 1


class RuleStore:
    """rules.json に保存されたルールの一覧。

    ファイルが存在しなければ空として扱い、最初の保存時に作成する。
    v1（ルール木）のファイルも読める。葉を木の順に並べた一覧として扱い、次の保存で v2 になる。
    新しいルールにはランダムな ID を振る。taken を渡すと、それとも被らない ID にする
    （消したルールの ID を再発行しないよう、呼び出し側はログに出た ID を渡す）。
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.items = self._load()

    def _load(self) -> list[Rule]:
        data = _read_json(self.path)
        if data is None:
            return []
        version = data.get("version")
        if version == 1:
            raw = list(_legacy_leaves(data.get("root")))
        elif version == FORMAT_VERSION:
            raw = data.get("rules")
            if not isinstance(raw, list):
                raise RuleError("rules must be a list")
        else:
            raise _version_error(self.path, version, FORMAT_VERSION)
        rules = [parse_rule(item) for item in raw]
        _check_unique(rule.id for rule in rules)
        return rules

    def save(self) -> None:
        """キー順・2 スペースインデント・末尾改行を固定して書き出す。"""
        _write_json(self.path, {"version": FORMAT_VERSION, "rules": [rule.to_dict() for rule in self.items]})

    def rules(self, scopes: list[str] | None = None) -> list[Rule]:
        """ルールを並び順で返す。scopes を渡すと、そのどれかを持つルールと全体共通のルールだけを返す。"""
        if not scopes:
            return list(self.items)
        wanted = set(normalize_scopes(scopes))
        return [rule for rule in self.items if not rule.scopes or wanted & set(rule.scopes)]

    def scopes(self) -> list[str]:
        """使われている範囲の名前を名前順で返す。"""
        return sorted({scope for rule in self.items for scope in rule.scopes})

    def get(self, rule_id: str) -> Rule | None:
        return next((rule for rule in self.items if rule.id == rule_id), None)

    def add_rule(
        self,
        text: str,
        scopes: list[str] | None = None,
        decision: str | None = None,
        source: str | None = None,
        taken: Collection[str] = (),
    ) -> Rule:
        """ルールを末尾に追加し、保存する。"""
        rule = self.new_rule(text, scopes, decision, source)
        self._issue(rule, taken)
        self.items.append(rule)
        self.save()
        return rule

    def replace_rule(
        self,
        old_id: str,
        text: str,
        scopes: list[str] | None = None,
        decision: str | None = None,
        source: str | None = None,
        taken: Collection[str] = (),
    ) -> tuple[Rule, Rule]:
        """old_id のルールを新しい ID のルールに置き換え、保存する。(古いルール, 新しいルール) を返す。

        新しいルールは古いルールと同じ位置に入る。文言の修正ではなく置き換えなので、ID は引き継がない。
        scopes を省くと古いルールの範囲を引き継ぐ。
        """
        index = self._index(old_id)
        old = self.items[index]
        rule = self.new_rule(text, old.scopes if scopes is None else scopes, decision, source)
        self._issue(rule, taken)
        self.items[index] = rule
        self.save()
        return old, rule

    def retire_rules(self, rule_ids: list[str]) -> list[Rule]:
        """ルールを消して保存する。存在しない ID が 1 つでもあれば何も消さずに RuleError を送出する。"""
        indexes = [self._index(rule_id) for rule_id in dict.fromkeys(rule_ids)]
        retired = [self.items[index] for index in indexes]
        self.items = [rule for index, rule in enumerate(self.items) if index not in indexes]
        self.save()
        return retired

    def change_scopes(self, rule_ids: list[str], add: list[str], remove: list[str]) -> list[Rule]:
        """ルールの範囲を足し引きして保存する。ID は変えない。"""
        add, remove = normalize_scopes(add), normalize_scopes(remove)
        if not add and not remove:
            raise RuleError("give at least one scope to add or remove")
        rules = [self.items[self._index(rule_id)] for rule_id in dict.fromkeys(rule_ids)]
        for rule in rules:
            rule.scopes = sorted((set(rule.scopes) | set(add)) - set(remove))
        self.save()
        return rules

    @staticmethod
    def new_rule(
        text: str,
        scopes: list[str] | None = None,
        decision: str | None = None,
        source: str | None = None,
    ) -> Rule:
        """ID のないルールを検証して作る。保存はしない。"""
        return Rule(
            id="",
            rule=validate_rule_text(text),
            scopes=normalize_scopes(scopes),
            decision=optional_token(decision, "decision"),
            source=optional_line(source, "source"),
        )

    def _index(self, rule_id: str) -> int:
        for index, rule in enumerate(self.items):
            if rule.id == rule_id:
                return index
        raise RuleError(f"unknown rule id: {rule_id}")

    def _issue(self, rule: Rule, taken: Collection[str]) -> None:
        rule.id = new_id("R", {*taken, *(r.id for r in self.items)})


class ProposalStore:
    """proposals.json に保存された、まだ決まっていない提案。

    決まった提案はここから消え、履歴は usage.jsonl に残る。
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.items = self._load()

    def _load(self) -> list[Proposal]:
        data = _read_json(self.path)
        if data is None:
            return []
        if data.get("version") != PROPOSALS_VERSION:
            raise _version_error(self.path, data.get("version"), PROPOSALS_VERSION)
        raw = data.get("proposals")
        if not isinstance(raw, list):
            raise RuleError("proposals must be a list")
        proposals = [parse_proposal(item) for item in raw]
        _check_unique(proposal.id for proposal in proposals)
        return proposals

    def save(self) -> None:
        _write_json(self.path, {"version": PROPOSALS_VERSION, "proposals": [p.to_dict() for p in self.items]})

    def get(self, proposal_id: str) -> Proposal | None:
        return next((proposal for proposal in self.items if proposal.id == proposal_id), None)

    def find_same(self, proposal: Proposal) -> Proposal | None:
        """中身が同じ提案が残っていれば返す。"""
        return next((p for p in self.items if p.same_content(proposal)), None)

    def add(self, proposal: Proposal, taken: Collection[str] = ()) -> Proposal:
        """新しい ID を振って追加し、保存する。taken はログに出たことのある ID。"""
        proposal.id = new_id("P", {*taken, *(p.id for p in self.items)})
        self.items.append(proposal)
        self.save()
        return proposal

    def remove(self, proposal_ids: list[str]) -> None:
        """決まった提案を消して保存する。"""
        self.items = [proposal for proposal in self.items if proposal.id not in proposal_ids]
        self.save()


def _version_error(path: Path, version: Any, supported: int) -> RuleError:
    """新しい k2down が書いたファイルなら、更新を促す。"""
    if type(version) is int and version > supported:
        return RuleError(
            f"{path.name} is version {version}, written by a newer k2down (this one reads up to {supported}); "
            "upgrade k2down"
        )
    return RuleError(f"unsupported {path.name} version: {version!r}")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuleError(f"{path.name} must be an object")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """一時ファイルに書いてから置き換える。途中で落ちても壊れたファイルを残さない。"""
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _check_unique(ids: Iterator[str] | Any) -> None:
    seen: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            raise RuleError(f"duplicate id: {item_id}")
        seen.add(item_id)


def _legacy_leaves(item: Any) -> Iterator[Any]:
    """v1 のルール木から葉（ルール）を木の順に取り出す。内部ノードは捨てる。"""
    if not isinstance(item, dict):
        raise RuleError(f"tree item must be an object: {item!r}")
    if "children" in item:
        children = item["children"]
        if not isinstance(children, list):
            raise RuleError(f"children of {item.get('id')} must be a list")
        for child in children:
            yield from _legacy_leaves(child)
    elif "rule" in item:
        yield item
    else:
        raise RuleError(f"tree item {item.get('id')} has neither children nor rule")
