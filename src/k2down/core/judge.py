"""判定インターフェース。

コアは「判定して」と頼むだけで、誰が判定するか（MCP sampling、Jev、フェイク等）を知らない。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from k2down.core.model import Rule


class Judge(Protocol):
    async def select(self, problem: str, rules: Sequence[Rule]) -> list[str]:
        """rules のうち problem に当てはまるものの ID を返す。"""
        ...
