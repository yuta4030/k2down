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
    Proposal,
    ProposalStore,
    Rule,
    RuleError,
    RuleStore,
    UsageLog,
    accept,
    add,
    build_report,
    decide,
    decline,
    escalate,
    locked,
    propose,
    record,
    replace,
    retire,
)
from k2down.core.report import MIN_DECISIONS
from k2down.core.service import OUTCOMES, REASONS

RULES_FILE = "rules.json"
PROPOSALS_FILE = "proposals.json"
USAGE_FILE = "usage.jsonl"
# ファイルを書かないコマンド。これ以外は store のディレクトリのロックを取ってから実行する。
READ_ONLY = ("list", "proposals", "report")

DESCRIPTION = """\
k2down: decision rules written in natural language, one line each.
k2down never judges by itself and never talks to the network.
The caller (typically an AI agent) reads the rules, decides which apply, and records the result.

Workflow for agents:
  1. k2down list [--scope S]                       # read the rules (with --scope: rules in S plus rules with no scope)
  2. decide which rules apply to the problem yourself, and give the decision a short ID (e.g. D123)
  3. k2down apply --decision D123 --problem "<summary>" R001 R003
  4. if no rule applies, or the applied rules point opposite ways, ask a human and record it:
     k2down escalate --decision D123 --problem "<summary>" --reason no_match
     k2down escalate --decision D123 --problem "<summary>" --reason conflict R003 R017
  5. once the human has decided, record whether the rules predicted it (you judge hit or miss):
     k2down decide --decision D123 --predicted "<what the rules said>" --actual "<what was decided>" --outcome miss
     use --outcome none when no rule predicted it; the human's answer becomes a new rule candidate
  6. if a human overrides an applied rule:
     k2down reject --decision D123 --problem "<summary>" R003
  7. if a new, general decision was made and no rule covered it, propose a rule; a human accepts or declines it:
     k2down propose add "<one-line rule>" --decision D123 [--scope S]
     k2down propose replace R012 "<new rule>" --decision D123
     k2down propose retire R020 --decision D123
     k2down proposals                              # pending proposals
     k2down accept P001                            # the human accepted: the rule change is applied
     k2down decline P002 --reason "<why>"          # the human declined: kept in the log for review
  8. maintenance, with a human:
     k2down report                                 # counts and candidates to drop, rewrite, split or add
     k2down scope R001 R002 --add implement        # scopes of existing rules (IDs stay)
     add / replace / retire do the same as accepting a proposal, without one

Output format (default):
  list      one rule per line, "<ID> <text>", followed by any of
            " [scopes: <S> <S>...]", " [decision: <D>]", " [source: <text>]", " [note: <path>]".
  scope     the changed rules, one per line, as in list
  add       the new rule ID
  replace   the new rule ID
  retire    "retired <ID> <ID>..."
  propose   the proposal ID (the same ID again if the same proposal is still pending)
  proposals one per line: "<P> add <text>", "<P> retire <ID>", "<P> replace <ID> <text>",
            followed by " [scopes: ...]", " [decision: <D>]", " [source: <text>]" if any
  accept    one line per proposal: "accepted <P> add <new ID>", "accepted <P> retire <ID>",
            "accepted <P> replace <ID> <new ID>"
  decline   "declined <P> <P>..."
  apply     "applied <ID> <ID>..."
  reject    "rejected <ID> <ID>..."
  decide    "decided <DECISION> <OUTCOME>"
  escalate  "escalated <DECISION> <REASON> [<ID>...]"
  report    sections of plain text; see the headings
  errors    "error: <message>" on stderr, exit status 1. Nothing is recorded on error.

Rule IDs look like R-k7m2q (R001 from older stores stays valid), proposal IDs like P-3xq9a.
Copy them exactly: a mistyped ID is an error, not another rule.
Commands that write wait for a lock on the store directory (.k2down.lock), so agents can run k2down at the same time.
Pass --json to get JSON instead (errors become {"error": "..."} on stderr).
Pass "-" instead of a text argument to read it from stdin.
The --decision ID is yours to choose (no spaces). It links apply, reject, escalate, decide and proposals.
A scope name has no spaces. A rule with no scope applies everywhere.
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

    list_ = sub.add_parser("list", help="print the rules", parents=[common])
    list_.add_argument("--scope", action="append", default=None, help="only rules in this scope (repeatable) and rules with no scope")

    scope = sub.add_parser("scope", help="add or remove scopes of rules (IDs stay)", parents=[common])
    scope.add_argument("rule_ids", nargs="+", metavar="RULE_ID")
    scope.add_argument("--add", action="append", default=[], metavar="SCOPE", help="scope to add (repeatable)")
    scope.add_argument("--remove", action="append", default=[], metavar="SCOPE", help="scope to remove (repeatable)")

    add = sub.add_parser("add", help="add a one-line rule and print its new ID", parents=[common])
    add.add_argument("rule", help='rule text (single line), or "-" for stdin')
    add_origin(add, scopes=True)

    replace = sub.add_parser("replace", help="replace a rule with a new one under a new ID", parents=[common])
    replace.add_argument("old_id", metavar="RULE_ID")
    replace.add_argument("rule", help='new rule text (single line), or "-" for stdin')
    add_origin(replace, scopes=True, inherit=True)

    retire = sub.add_parser("retire", help="remove rules (their IDs are never reused)", parents=[common])
    retire.add_argument("rule_ids", nargs="+", metavar="RULE_ID")

    propose = sub.add_parser("propose", help="propose a rule change for a human to accept or decline", parents=[common])
    kinds = propose.add_subparsers(dest="kind", required=True, metavar="KIND")
    p_add = kinds.add_parser("add", help="propose a new rule", parents=[common])
    p_add.add_argument("rule", help='rule text (single line), or "-" for stdin')
    add_origin(p_add, scopes=True)
    p_retire = kinds.add_parser("retire", help="propose removing a rule", parents=[common])
    p_retire.add_argument("rule_id", metavar="RULE_ID")
    add_origin(p_retire, scopes=False)
    p_replace = kinds.add_parser("replace", help="propose replacing a rule", parents=[common])
    p_replace.add_argument("rule_id", metavar="RULE_ID")
    p_replace.add_argument("rule", help='new rule text (single line), or "-" for stdin')
    add_origin(p_replace, scopes=True, inherit=True)

    sub.add_parser("proposals", help="print pending proposals", parents=[common])

    accept = sub.add_parser("accept", help="accept proposals and apply them to the rules", parents=[common])
    accept.add_argument("proposal_ids", nargs="+", metavar="PROPOSAL_ID")

    decline = sub.add_parser("decline", help="decline proposals (kept in the log)", parents=[common])
    decline.add_argument("proposal_ids", nargs="+", metavar="PROPOSAL_ID")
    decline.add_argument("--reason", default=None, help="why it was declined (one line)")

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

    escalate = sub.add_parser("escalate", help="record that the rules could not decide and a human was asked", parents=[common])
    escalate.add_argument("--decision", required=True, help="decision ID chosen by the caller (no spaces)")
    escalate.add_argument("--problem", required=True, help='short summary of the problem, or "-" for stdin')
    escalate.add_argument("--reason", required=True, choices=REASONS, help="no_match: no rule applied, conflict: rules conflicted")
    escalate.add_argument("rule_ids", nargs="*", metavar="RULE_ID", help="the conflicting rules (conflict only)")

    report = sub.add_parser("report", help="count the usage log and list maintenance candidates", parents=[common])
    report.add_argument("--since", default=None, help="only count events on or after this date (YYYY-MM-DD)")
    report.add_argument(
        "--min-decisions",
        type=int,
        default=MIN_DECISIONS,
        help=f"a never-applied rule is a drop candidate only after this many decisions since it was added (default: {MIN_DECISIONS})",
    )

    return parser


def add_origin(cmd: argparse.ArgumentParser, scopes: bool, inherit: bool = False) -> None:
    """ルールや提案の範囲と出どころの引数を足す。"""
    if scopes:
        default = " (default: the scopes of the replaced rule)" if inherit else ""
        cmd.add_argument("--scope", action="append", default=None, help=f"scope of the rule (repeatable){default}")
    cmd.add_argument("--decision", default=None, help="decision ID the rule came from (no spaces)")
    cmd.add_argument("--source", default=None, help="other origin that is not a decision ID (one line)")


def run(args: argparse.Namespace) -> tuple[Any, str]:
    """コマンドを実行し、(JSON 用の値, テキスト出力) を返す。"""
    data_dir = Path(args.dir)
    store = RuleStore(data_dir / RULES_FILE)

    if args.command == "list":
        rules = store.rules(args.scope)
        return {"rules": [rule.to_dict() for rule in rules], "scopes": store.scopes()}, render_rules(rules)
    if args.command == "scope":
        rules = store.change_scopes(args.rule_ids, args.add, args.remove)
        return {"rules": [rule.to_dict() for rule in rules]}, render_rules(rules)

    log = UsageLog(data_dir / USAGE_FILE)
    proposals = ProposalStore(data_dir / PROPOSALS_FILE)
    if args.command == "add":
        rule = add(store, log, read_text(args.rule), args.scope, args.decision, args.source)
        return {"id": rule.id}, rule.id
    if args.command == "replace":
        old, new = replace(store, log, args.old_id, read_text(args.rule), args.scope, args.decision, args.source)
        return {"id": new.id, "replaced": old.id}, new.id
    if args.command == "propose":
        proposal, created = propose(
            store,
            proposals,
            log,
            args.kind,
            rule=None if args.kind == "retire" else read_text(args.rule),
            rule_id=None if args.kind == "add" else args.rule_id,
            scopes=getattr(args, "scope", None),
            decision=args.decision,
            source=args.source,
        )
        return {"id": proposal.id, "created": created}, proposal.id
    if args.command == "proposals":
        items = proposals.items
        return {"proposals": [p.to_dict() for p in items]}, "\n".join(render_proposal(p) for p in items)
    if args.command == "accept":
        results = accept(store, proposals, log, args.proposal_ids)
        lines = [
            " ".join(["accepted", r["proposal"], r["kind"], r["rule_id"], *([r["replaced_by"]] if "replaced_by" in r else [])])
            for r in results
        ]
        return {"accepted": results}, "\n".join(lines)
    if args.command == "decline":
        declined = decline(proposals, log, args.proposal_ids, args.reason)
        return {"declined": [p.to_dict() for p in declined]}, " ".join(["declined", *(p.id for p in declined)])
    if args.command == "retire":
        rules = retire(store, log, args.rule_ids)
        return {"retired": [rule.to_dict() for rule in rules]}, " ".join(["retired", *(rule.id for rule in rules)])
    if args.command == "decide":
        fields = decide(log, args.decision, read_text(args.actual), args.outcome, args.predicted, args.problem)
        return {"decided": fields}, f"decided {fields['decision']} {fields['outcome']}"
    if args.command == "escalate":
        rules = escalate(store, log, args.decision, read_text(args.problem), args.reason, args.rule_ids)
        data = {"decision": args.decision, "reason": args.reason, "rule_ids": [rule.id for rule in rules]}
        return {"escalated": data}, " ".join(["escalated", args.decision, args.reason, *data["rule_ids"]])
    if args.command == "report":
        since = None if args.since is None else parse_date(args.since)
        data = build_report(store.rules(), log.read(), since, proposals.items, args.min_decisions)
        return data, "\n".join(render_report(data))

    event = {"apply": "applied", "reject": "rejected"}[args.command]
    rules = record(store, log, event, args.rule_ids, read_text(args.problem), args.decision)
    return {event: [rule.to_dict() for rule in rules]}, " ".join([event, *(rule.id for rule in rules)])


def render_rules(rules: list[Rule]) -> str:
    return "\n".join(
        f"{rule.id} {rule.rule}{render_origin(rule.scopes, rule.decision, rule.source)}"
        + ("" if rule.note is None else f" [note: {one_line(rule.note)}]")
        for rule in rules
    )


def render_proposal(proposal: Proposal) -> str:
    words = [proposal.id, proposal.kind, *(w for w in (proposal.rule_id, proposal.rule) if w is not None)]
    return " ".join(words) + render_origin(proposal.scopes, proposal.decision, proposal.source)


def render_origin(scopes: list[str], decision: str | None, source: str | None) -> str:
    text = f" [scopes: {' '.join(scopes)}]" if scopes else ""
    if decision is not None:
        text += f" [decision: {decision}]"
    if source is not None:
        text += f" [source: {one_line(source)}]"
    return text


def render_report(data: dict[str, Any]) -> list[str]:
    rules = {row["id"]: row for row in data["rules"]}
    d = data["decisions"]
    lines = [
        f"since {data['since'] or 'the beginning'}",
        f"decisions {d['decided']}: hit {d['hit']}, miss {d['miss']}, none {d['none']}",
        "proposals: " + ", ".join(f"{key} {value}" for key, value in data["proposals"].items()),
    ]
    sections = [
        (
            "rules (ID applied hit miss rejected decisions-since-added text):",
            [
                f"{r['id']} {r['applied']} {r['hit']} {r['miss']} {r['rejected']} {r['decisions']} {r['rule']}"
                for r in data["rules"]
            ],
        ),
        (
            f"drop candidates (never applied in {data['min_decisions']}+ decisions since added; ID decisions text):",
            [f"{rule_id} {rules[rule_id]['decisions']} {rules[rule_id]['rule']}" for rule_id in data["drop_candidates"]],
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
                + (f" | proposals: {' '.join(c['proposals'])}" if c["proposals"] else "")
                for c in data["new_rule_candidates"]
            ],
        ),
        (
            "declined proposals (proposal kind target text | reason):",
            [
                " ".join(str(d[k]) for k in ("proposal", "kind", "rule_id", "rule") if d.get(k) is not None)
                + f" | {d.get('reason') or '-'}"
                for d in data["declined_proposals"]
            ],
        ),
        (
            "decided by rules per day (date hit/decided ratio):",
            [f"{day['date']} {day['hit']}/{day['decided']} {day['ratio']:.2f}" for day in data["daily"]],
        ),
    ]
    for title, items in sections:
        lines += ["", title, *(f"  {item}" for item in items or ["(none)"])]
    return lines


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
        if args.command in READ_ONLY:
            data, text = run(args)
        else:
            with locked(args.dir):
                data, text = run(args)
    except (RuleError, ValueError, OSError) as e:
        message = json.dumps({"error": str(e)}, ensure_ascii=False) if as_json else f"error: {one_line(str(e))}"
        print(message, file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2) if as_json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
