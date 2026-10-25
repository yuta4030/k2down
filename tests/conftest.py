from __future__ import annotations

from collections.abc import Sequence

import pytest

from k2down.core import Rule


class FakeJudge:
    """固定の ID を返すフェイク判定器。通信しない。"""

    def __init__(self, ids: Sequence[str]) -> None:
        self.ids = list(ids)
        self.calls: list[tuple[str, list[str]]] = []

    async def select(self, problem: str, rules: Sequence[Rule]) -> list[str]:
        self.calls.append((problem, [rule.id for rule in rules]))
        return list(self.ids)


@pytest.fixture(autouse=True)
def sequential_ids(monkeypatch):
    """テストでは ID を R-00001, R-00002 ... と順に振る（本番はランダム）。"""
    counters: dict[str, int] = {}

    def fake_random_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]:05d}"

    monkeypatch.setattr("k2down.core.model.random_id", fake_random_id)
