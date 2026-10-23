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
from datetime import date
from pathlib import Path
from typing import Any

from k2down import __version__
from k2down.core import (
    Node,
    Rule,
    RuleError,
    RuleStore,
    UsageLog,
    build_report,
    decide,
    escalate,
    record,
    replace,
    retire,
)
from k2down.core.service import OUTCOMES, REASONS

RULES_FILE = "rules.json"
USAGE_FILE = "usage.jsonl"

DESCRIPTION = """\
k2down: decision rules written in natural language, one line each.
k2down never judges by itself and never talks to the network.
The caller (typically an AI agent) reads the rules, decides which apply, and records the result.

Workflow for agents:
  1. k2down list                                   # read all rules
  2. decide which rules apply to the problem yourself, and give the decision a short ID (e.g. D123)
  3. k2down apply --decision D123 --problem "<summary>" R001 R003
  4. if no rule applies, or the applied rules point opposite ways, ask a human and record it:
     k2down escalate --decision D123 --problem "<summary>" --reason no_match
     k2down escalate --decision D123 --problem "<summary>" --reason conflict R003 R017
  5. once the human has decided, record whether the rules predicted it (you judge hit or miss):
     k2down decide --decision D123 --predicted "<what the rules said>" --actual "<what was decided>" --outcome miss
     use --outcome none when no rule predicted it; the human's answer becomes a new rule candidate
     add --rationale "<why the human decided so>" (one line); it is the draft of the next rule
     if the decision cannot be undone, ask a human even when a rule applies,
     and pass --irreversible to escalate and decide
  6. if a human overrides an applied rule:
     k2down reject --decision D123 --problem "<summary>" R003
  7. if a new, general decision was made and no rule covered it:
     k2down add "<one-line rule>" --source "<decision or session it came from>"
  8. maintenance, with a human:
     k2down report                                 # counts and candidates to drop, rewrite, split or add,
                                                   # and rules whose text names an ID that is gone
     k2down replace R012 "<new rule>"              # new ID; the log maps R012 to it
     k2down retire R020                            # remove a rule; its ID is never reused

Output format (default):
  list      one item per line, "<ID> <text>", indented by 2 spaces per tree level.
            N### lines are groups (summary), R### lines are rules.
            A note path follows as " [note: <path>]", a source as " [source: <text>]".
  add       the new rule ID
  replace   the new rule ID
  retire    "retired <ID> <ID>..."
  apply     "applied <ID> <ID>..."
  reject    "rejected <ID> <ID>..."
  decide    "decided <DECISION> <OUTCOME>"
  escalate  "escalated <DECISION> <REASON> [<ID>...]"
  report    sections of plain text; see the headings
  errors    "error: <message>" on stderr, exit status 1. Nothing is recorded on error.
Pass --json to get JSON instead (errors become {"error": "..."} on stderr).
Pass "-" instead of a text argument to read it from stdin.
The --decision ID is yours to choose (no spaces). It links apply, reject, escalate and decide.
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
    add.add_argument("--source", default=None, help="where the rule came from (decision, session; one line)")

    replace = sub.add_parser("replace", help="replace a rule with a new one under a new ID", parents=[common])
    replace.add_argument("old_id", metavar="RULE_ID")
    replace.add_argument("rule", help='new rule text (single line), or "-" for stdin')
    replace.add_argument("--source", default=None, help="where the new rule came from (one line)")

    retire = sub.add_parser("retire", help="remove rules (their IDs are never reused)", parents=[common])
    retire.add_argument("rule_ids", nargs="+", metavar="RULE_ID")

    for name, help_text in (
        ("apply", "record that rules were applied to a problem"),
        ("reject", "record that a human rejected/overrode applied rules"),
    ):
        cmd = sub.add_parser(name, help=help_text, parents=[common])
        cmd.add_argument("--problem", required=True, help='short summary of the problem, or "-" for stdin')
        cmd.add_argument("--decision", default=None, help="decision ID chosen by the caller (no spaces)")
        cmd.add_argument("rule_ids", nargs="+", metavar="RULE_ID")

    decide = sub.add_parser("decide", help="record the human decision and whether the rules predicted it", parents=[common])
    decide.add_argument("--decision", required=True, help="decision ID chosen by the caller (no spaces)")
    decide.add_argument("--actual", required=True, help='what was decided, or "-" for stdin')
    decide.add_argument("--outcome", required=True, choices=OUTCOMES, help="hit: predicted, miss: wrong, none: no prediction")
    decide.add_argument("--predicted", default=None, help="what the applied rules predicted")
    decide.add_argument("--problem", default=None, help="short summary of the problem")
    decide.add_argument("--rationale", default=None, help='why the human decided so (one line), or "-" for stdin')
    decide.add_argument("--irreversible", action="store_true", help="the decision cannot be undone")

    escalate = sub.add_parser("escalate", help="record that the rules could not decide and a human was asked", parents=[common])
    escalate.add_argument("--decision", required=True, help="decision ID chosen by the caller (no spaces)")
    escalate.add_argument("--problem", required=True, help='short summary of the problem, or "-" for stdin')
    escalate.add_argument("--reason", required=True, choices=REASONS, help="no_match: no rule applied, conflict: rules conflicted")
    escalate.add_argument("rule_ids", nargs="*", metavar="RULE_ID", help="the conflicting rules (conflict only)")
    escalate.add_argument("--irreversible", action="store_true", help="the decision cannot be undone")

    report = sub.add_parser("report", help="count the usage log and list maintenance candidates", parents=[common])
    report.add_argument("--since", default=None, help="only count events on or after this date (YYYY-MM-DD)")

    return parser


def run(args: argparse.Namespace) -> tuple[Any, str]:
    """コマンドを実行し、(JSON 用の値, テキスト出力) を返す。"""
    data_dir = Path(args.dir)
    store = RuleStore(data_dir / RULES_FILE)

    if args.command == "list":
        data = {"rules": [{**rule.to_dict(), "parent": parent} for parent, rule in store.rules_with_parent()]}
        return data, "\n".join(render_tree(store.root))
    if args.command == "add":
        rule_id = store.add_rule(read_text(args.rule), args.parent, args.source).id
        return {"id": rule_id}, rule_id

    log = UsageLog(data_dir / USAGE_FILE)
    if args.command == "replace":
        old, new = replace(store, log, args.old_id, read_text(args.rule), args.source)
        return {"id": new.id, "replaced": old.id}, new.id
    if args.command == "retire":
        rules = retire(store, log, args.rule_ids)
        return {"retired": [rule.to_dict() for rule in rules]}, " ".join(["retired", *(rule.id for rule in rules)])
    if args.command == "decide":
        rationale = None if args.rationale is None else read_text(args.rationale)
        fields = decide(
            log, args.decision, read_text(args.actual), args.outcome, args.predicted, args.problem, rationale, args.irreversible
        )
        return {"decided": fields}, f"decided {fields['decision']} {fields['outcome']}"
    if args.command == "escalate":
        rules = escalate(store, log, args.decision, read_text(args.problem), args.reason, args.rule_ids, args.irreversible)
        data = {"decision": args.decision, "reason": args.reason, "rule_ids": [rule.id for rule in rules]}
        return {"escalated": data}, " ".join(["escalated", args.decision, args.reason, *data["rule_ids"]])
    if args.command == "report":
        since = None if args.since is None else parse_date(args.since)
        data = build_report(store.rules(), log.read(), since)
        return data, "\n".join(render_report(data))

    event = {"apply": "applied", "reject": "rejected"}[args.command]
    rules = record(store, log, event, args.rule_ids, read_text(args.problem), args.decision)
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
    if rule.source is not None:
        text += f" [source: {one_line(rule.source)}]"
    return text


def render_report(data: dict[str, Any]) -> list[str]:
    rules = {row["id"]: row for row in data["rules"]}
    d = data["decisions"]
    lines = [
        f"since {data['since'] or 'the beginning'}",
        f"decisions {d['decided']}: hit {d['hit']}, miss {d['miss']}, none {d['none']}",
    ]
    sections = [
        (
            "rules (ID applied hit miss rejected text):",
            [f"{r['id']} {r['applied']} {r['hit']} {r['miss']} {r['rejected']} {r['rule']}" for r in data["rules"]],
        ),
        (
            "drop candidates (never applied):",
            [f"{rule_id} {rules[rule_id]['rule']}" for rule_id in data["drop_candidates"]],
        ),
        (
            "rewrite candidates (miss + rejected, most first):",
            [
                f"{rule_id} {rules[rule_id]['miss'] + rules[rule_id]['rejected']} {rules[rule_id]['rule']}"
                for rule_id in data["rewrite_candidates"]
            ],
        ),
        (
            "conflict candidates (applied together and missed, or escalated as conflict; check whether they really conflict):",
            [f"{' '.join(c['rule_ids'])} in {' '.join(c['decisions'])}" for c in data["conflict_candidates"]],
        ),
        (
            "new rule candidates (decided with outcome none):",
            [
                f"{c['decision']} problem: {c['problem'] or '-'} | actual: {c['actual'] or '-'}"
                + (f" | rationale: {c['rationale']}" if c["rationale"] else "")
                for c in data["new_rule_candidates"]
            ],
        ),
        (
            "irreversible decisions (decision outcome problem):",
            [f"{c['decision']} {c['outcome'] or '-'} {c['problem'] or '-'}" for c in data["irreversible_decisions"]],
        ),
        (
            "stale references (rule text names an ID that no longer exists; ID->replacement, or ID->gone):",
            [f"{c['id']} {' '.join(map(render_ref, c['refs']))} {c['rule']}" for c in data["stale_references"]],
        ),
        (
            "decided by rules per day (date hit/decided ratio):",
            [f"{day['date']} {day['hit']}/{day['decided']} {day['ratio']:.2f}" for day in data["daily"]],
        ),
    ]
    for title, items in sections:
        lines += ["", title, *(f"  {item}" for item in items or ["(none)"])]
    return lines


def render_ref(ref: dict[str, Any]) -> str:
    return f"{ref['id']}->{ref['replaced_by'] or 'gone'}"


def one_line(text: str) -> str:
    return " ".join(text.split())


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"date must be YYYY-MM-DD: {value}") from None


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
