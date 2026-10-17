"""MCP サーバー本体。

使い方: k2down-mcp [--dir DIR]
DIR（省略時は環境変数 K2DOWN_DIR、それもなければカレントディレクトリ）の
rules.json と usage.jsonl を読み書きする。
"""

# ツールの型注釈は SDK が実行時に評価するため、ここでは `from __future__ import annotations` を使わない。
import argparse
import os
from pathlib import Path
from typing import Annotated, Any

from mcp import types
from mcp.server.mcpserver import MCPServer, Resolve, Sample

from k2down import __version__
from k2down.core import RuleStore, UsageLog, find_rules
from k2down.mcp.judge import SampledJudge, sampling_request

RULES_FILE = "rules.json"
USAGE_FILE = "usage.jsonl"


def create_server(data_dir: str | os.PathLike[str]) -> MCPServer:
    data_dir = Path(data_dir)
    server = MCPServer(
        name="k2down",
        version=__version__,
        instructions=(
            "Decision rules written in natural language. Use find_rules before deciding, add_rule to record a new decision. "
            "When find_rules returns escalate: true, no rule applies: ask a human."
        ),
    )

    def judgement(problem: str) -> Sample | None:
        # ルールが無い・問題文が空のときはホストに頼まない。
        rules = RuleStore(data_dir / RULES_FILE).rules()
        if not rules or not problem.strip():
            return None
        return sampling_request(problem.strip(), rules)

    @server.tool(name="find_rules")
    async def find_rules_tool(
        problem: str,
        sampled: Annotated[types.CreateMessageResult | None, Resolve(judgement)],
    ) -> dict[str, Any]:
        """問題文に当てはまる決断ルールを返す。当てはまるルールがなければ escalate が true になる（人に聞く）。"""
        store = RuleStore(data_dir / RULES_FILE)
        log = UsageLog(data_dir / USAGE_FILE)
        rules = await find_rules(store, SampledJudge(sampled), problem, log)
        return {"rules": [rule.to_dict() for rule in rules], "escalate": not rules}

    @server.tool(name="add_rule")
    def add_rule_tool(rule: str, parent_id: str | None = None) -> dict[str, str]:
        """自然言語 1 行の決断ルールを追加し、新しい ID を返す。"""
        store = RuleStore(data_dir / RULES_FILE)
        added = store.add_rule(rule, parent_id)
        return {"id": added.id}

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="k2down-mcp", description="k2down MCP server (stdio)")
    parser.add_argument("--dir", default=os.environ.get("K2DOWN_DIR", "."), help="rules.json を置くディレクトリ")
    args = parser.parse_args(argv)
    create_server(args.dir).run("stdio")


if __name__ == "__main__":
    main()
