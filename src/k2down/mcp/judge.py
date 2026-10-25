"""MCP sampling でホスト側の LLM に判定を依頼する判定器。

サーバー自身は外部に通信せず、stdio の相手（ホスト）にだけ頼む。
sampling の往復は SDK の Resolve/Sample に任せる（プロトコル版ごとの違いを SDK が吸収する）。
ここでは依頼文の組み立てと、返ってきた応答の解釈だけを行う。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from mcp import types
from mcp.server.mcpserver import Sample

from k2down.core.model import RULE_ID, Rule

SYSTEM_PROMPT = (
    "You are a strict rule matcher. Given a problem and a list of decision rules, "
    "return the IDs of the rules that apply to the problem. "
    'Answer with a JSON array of rule IDs only, e.g. ["R001", "R003"]. '
    "Answer [] if no rule applies."
)
MAX_TOKENS = 512


def sampling_request(problem: str, rules: Sequence[Rule]) -> Sample:
    listing = "\n".join(f"{rule.id}: {rule.rule}" for rule in rules)
    prompt = f"# Problem\n{problem}\n\n# Rules\n{listing}"
    return Sample(
        [types.SamplingMessage(role="user", content=types.TextContent(type="text", text=prompt))],
        system_prompt=SYSTEM_PROMPT,
        max_tokens=MAX_TOKENS,
        temperature=0,
    )


class SampledJudge:
    """sampling の応答を判定結果として返す判定器。"""

    def __init__(self, result: types.CreateMessageResult | None) -> None:
        self.result = result

    async def select(self, problem: str, rules: Sequence[Rule]) -> list[str]:
        if self.result is None or not isinstance(self.result.content, types.TextContent):
            return []
        return parse_ids(self.result.content.text)


def parse_ids(text: str) -> list[str]:
    """応答から ID を取り出す。JSON 配列を優先し、だめなら ID らしき文字列を拾う。"""
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(data, list):
                return [item for item in data if isinstance(item, str) and RULE_ID.match(item)]
    return [item for item in re.findall(r"R-?[0-9a-z]+", text) if RULE_ID.match(item)]
