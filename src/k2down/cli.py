"""k2down のコマンドライン。

主な利用者はホスト側の AI エージェント（Claude Code 等）。出力は常に JSON 1 個を stdout に書く。
k2down 自身は判定しない。ルールを渡し、当てはまるかどうかはホスト側が決めて結果を記録させる。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from k2down import __version__
from k2down.core import RuleError, RuleStore, UsageLog, record

RULES_FILE = "rules.json"
USAGE_FILE = "usage.jsonl"

DESCRIPTION = """\
k2down: decision rules written in natural language, one line each.
k2down never judges by itself and never talks to the network.
The caller (typically an AI agent) reads the rules, decides which apply, and records the result.

Workflow for agents:
  1. k2down list                                  # read all rules (JSON)
  2. decide which rules apply to the problem yourself
  3. k2down apply --problem "<summary>" R001 R003  # record the rules you applied
  4. if a human overrides an applied rule:
     k2down reject --problem "<summary>" R003
  5. if a new, general decision was made and no rule covered it:
     k2down add "<one-line rule>"                  # prints the new ID

Output is a single JSON value on stdout. On error, exit status is non-zero and
{"error": "..."} is written to stderr. Pass "-" instead of a text argument to read it from stdin.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="k2down", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"k2down {__version__}")
    parser.add_argument(
        "--dir",
        default=os.environ.get("K2DOWN_DIR", "."),
        help="directory holding rules.json and usage.jsonl (default: $K2DOWN_DIR or current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("list", help="print all rules as JSON")

    add = sub.add_parser("add", help="add a one-line rule and print its new ID")
    add.add_argument("rule", help='rule text (single line), or "-" for stdin')
    add.add_argument("--parent", default=None, help="parent node ID (default: root N000)")

    for name, help_text in (
        ("apply", "record that rules were applied to a problem"),
        ("reject", "record that a human rejected/overrode applied rules"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--problem", required=True, help='short summary of the problem, or "-" for stdin')
        cmd.add_argument("rule_ids", nargs="+", metavar="RULE_ID")

    return parser


def run(args: argparse.Namespace) -> Any:
    data_dir = Path(args.dir)
    store = RuleStore(data_dir / RULES_FILE)

    if args.command == "list":
        return {
            "rules": [
                {**rule.to_dict(), "parent": parent} for parent, rule in store.rules_with_parent()
            ]
        }
    if args.command == "add":
        return {"id": store.add_rule(read_text(args.rule), args.parent).id}

    event = {"apply": "applied", "reject": "rejected"}[args.command]
    rules = record(store, UsageLog(data_dir / USAGE_FILE), event, args.rule_ids, read_text(args.problem))
    return {event: [rule.to_dict() for rule in rules]}


def read_text(value: str) -> str:
    return sys.stdin.read() if value == "-" else value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (RuleError, ValueError, OSError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
