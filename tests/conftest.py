from __future__ import annotations

from collections.abc import Sequence

from k2down.core import Rule


class FakeJudge:
    """固定の ID を返すフェイク判定器。通信しない。"""

    def __init__(self, ids: Sequence[str]) -> None:
        self.ids = list(ids)
        self.calls: list[tuple[str, list[str]]] = []

    async def select(self, problem: str, rules: Sequence[Rule]) -> list[str]:
        self.calls.append((problem, [rule.id for rule in rules]))
        return list(self.ids)
