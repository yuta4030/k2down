"""k2down のコマンドライン。

主な利用者はホスト側の AI エージェント（Claude Code 等）。
既定の出力は LLM が読みやすく、トークンの少ないプレーンテキスト。--json で JSON を返す。
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
from k2down.core import Node, Rule, RuleError, RuleStore, UsageLog, record

RULES_FILE = "rules.json"
USAGE_FILE = "usage.jsonl"

DESCRIPTION = """\
k2down: decision rules written in natural language, one line each.
k2down never judges by itself and never talks to the network.
The caller (typically an AI agent) reads the rules, decides which apply, and records the result.

Workflow for agents:
  1. k2down list                                  # read all rules
  2. decide which rules apply to the problem yourself
  3. k2down apply --problem "<summary>" R001 R003  # record the rules you applied
  4. if a human overrides an applied rule:
     k2down reject --problem "<summary>" R003
  5. if a new, general decision was made and no rule covered it:
     k2down add "<one-line rule>"                  # prints the new ID

Output format (default):
  list    one item per line, "<ID> <text>", indented by 2 spaces per tree level.
          N### lines are groups (summary), R### lines are rules. A note path follows as " [note: <path>]".
  add     the new rule ID
  apply   "applied <ID> <ID>..."
  reject  "rejected <ID> <ID>..."
  errors  "error: <message>" on stderr, exit status 1. Nothing is recorded on error.
Pass --json to get JSON instead (errors become {"error": "..."} on stderr).
Pass "-" instead of a text argument to read it from stdin.
"""


def build_parser() -> argparse.ArgumentParser:
    # --json はサブコマンドの前後どちらに置いても効くようにする。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="output JSON")

    parser = argparse.ArgumentParser(
        prog="k2down",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"k2down {__version__}")
    parser.add_argument(
        "--dir",
        default=os.environ.get("K2DOWN_DIR", "."),
        help="directory holding rules.json and usage.jsonl (default: $K2DOWN_DIR or current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("list", help="print all rules", parents=[common])

    add = sub.add_parser("add", help="add a one-line rule and print its new ID", parents=[common])
    add.add_argument("rule", help='rule text (single line), or "-" for stdin')
    add.add_argument("--parent", default=None, help="parent node ID (default: root N000)")

    for name, help_text in (
        ("apply", "record that rules were applied to a problem"),
        ("reject", "record that a human rejected/overrode applied rules"),
    ):
        cmd = sub.add_parser(name, help=help_text, parents=[common])
        cmd.add_argument("--problem", required=True, help='short summary of the problem, or "-" for stdin')
        cmd.add_argument("rule_ids", nargs="+", metavar="RULE_ID")

    return parser


def run(args: argparse.Namespace) -> tuple[Any, str]:
    """コマンドを実行し、(JSON 用の値, テキスト出力) を返す。"""
    data_dir = Path(args.dir)
    store = RuleStore(data_dir / RULES_FILE)

    if args.command == "list":
        data = {"rules": [{**rule.to_dict(), "parent": parent} for parent, rule in store.rules_with_parent()]}
        return data, "\n".join(render_tree(store.root))
    if args.command == "add":
        rule_id = store.add_rule(read_text(args.rule), args.parent).id
        return {"id": rule_id}, rule_id

    event = {"apply": "applied", "reject": "rejected"}[args.command]
    rules = record(store, UsageLog(data_dir / USAGE_FILE), event, args.rule_ids, read_text(args.problem))
    return {event: [rule.to_dict() for rule in rules]}, " ".join([event, *(rule.id for rule in rules)])


def render_tree(node: Node, depth: int = 0) -> list[str]:
    lines = [f"{'  ' * depth}{node.id} {one_line(node.summary)}".rstrip()]
    for child in node.children:
        if isinstance(child, Node):
            lines.extend(render_tree(child, depth + 1))
        else:
            lines.append(f"{'  ' * (depth + 1)}{render_rule(child)}")
    return lines


def render_rule(rule: Rule) -> str:
    text = f"{rule.id} {rule.rule}"
    if rule.note is not None:
        text += f" [note: {one_line(rule.note)}]"
    return text


def one_line(text: str) -> str:
    return " ".join(text.split())


def read_text(value: str) -> str:
    return sys.stdin.read() if value == "-" else value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_json = getattr(args, "json", False)
    try:
        data, text = run(args)
    except (RuleError, ValueError, OSError) as e:
        message = json.dumps({"error": str(e)}, ensure_ascii=False) if as_json else f"error: {one_line(str(e))}"
        print(message, file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2) if as_json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
