import io
import json

import pytest

from k2down.cli import main
from k2down.core import ProposalStore, RuleError, RuleStore, UsageLog, accept, build_report, decide, decline, propose


@pytest.fixture
def env(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    for text in ("足すより引く", "区別すべきは区別する"):
        store.add_rule(text)
    return store, ProposalStore(tmp_path / "proposals.json"), UsageLog(tmp_path / "usage.jsonl")


def events(log, *kinds):
    return [r for r in log.read() if r["event"] in kinds]


def test_propose_is_idempotent_and_ids_are_not_reused(env, tmp_path):
    store, proposals, log = env
    p1, created = propose(store, proposals, log, "add", rule="ログは JSON で出す", decision="I3-2")
    assert (p1.id, created) == ("P001", True)
    again, created = propose(store, proposals, log, "add", rule="  ログは JSON で出す ", decision="I3-9")
    assert (again.id, created) == ("P001", False)
    # 範囲が違えば別の提案
    assert propose(store, proposals, log, "add", rule="ログは JSON で出す", scopes=["implement"])[0].id == "P002"

    accept(store, proposals, log, ["P001", "P002"])
    reloaded = ProposalStore(tmp_path / "proposals.json")
    assert reloaded.items == []
    assert propose(store, reloaded, log, "retire", rule_id="R001")[0].id == "P003"
    assert [r["proposal"] for r in events(log, "proposed")] == ["P001", "P002", "P003"]


def test_accept_applies_each_kind(env):
    store, proposals, log = env
    store.change_scopes(["R002"], add=["review"], remove=[])
    propose(store, proposals, log, "add", rule="c", scopes=["plan"], decision="I1", source="人の方針")
    propose(store, proposals, log, "retire", rule_id="R001", decision="I2")
    propose(store, proposals, log, "replace", rule_id="R002", rule="区別できるなら区別する", decision="I3")

    assert accept(store, proposals, log, ["P003", "P001", "P002"]) == [
        {"proposal": "P003", "kind": "replace", "rule_id": "R002", "replaced_by": "R003"},
        {"proposal": "P001", "kind": "add", "rule_id": "R004"},
        {"proposal": "P002", "kind": "retire", "rule_id": "R001"},
    ]
    assert [r.to_dict() for r in store.rules()] == [
        {"id": "R003", "rule": "区別できるなら区別する", "scopes": ["review"], "decision": "I3"},
        {"id": "R004", "rule": "c", "scopes": ["plan"], "decision": "I1", "source": "人の方針"},
    ]
    changes = [(r["event"], r.get("proposal")) for r in events(log, "accepted", "added", "replaced", "retired")]
    assert changes == [
        ("accepted", "P003"),
        ("replaced", "P003"),
        ("accepted", "P001"),
        ("added", "P001"),
        ("accepted", "P002"),
        ("retired", "P002"),
    ]


@pytest.mark.parametrize(
    ("ids", "message"),
    [
        (["P001", "P999"], "P999"),
        (["P001", "P002"], "same rule"),
    ],
)
def test_accept_changes_nothing_on_error(env, tmp_path, ids, message):
    store, proposals, log = env
    propose(store, proposals, log, "retire", rule_id="R001")
    propose(store, proposals, log, "replace", rule_id="R001", rule="x")
    before = [(tmp_path / name).read_text(encoding="utf-8") for name in ("rules.json", "proposals.json", "usage.jsonl")]
    with pytest.raises(RuleError, match=message):
        accept(store, proposals, log, ids)
    after = [(tmp_path / name).read_text(encoding="utf-8") for name in ("rules.json", "proposals.json", "usage.jsonl")]
    assert after == before


def test_accept_fails_when_target_is_gone(env):
    store, proposals, log = env
    propose(store, proposals, log, "retire", rule_id="R001")
    propose(store, proposals, log, "replace", rule_id="R001", rule="x")
    accept(store, proposals, log, ["P002"])
    with pytest.raises(RuleError, match=r"R001 \(replaced by R003\)"):
        accept(store, proposals, log, ["P001"])
    assert [p.id for p in proposals.items] == ["P001"]


def test_settled_proposal_ids_explain_themselves(env):
    store, proposals, log = env
    propose(store, proposals, log, "add", rule="a")
    propose(store, proposals, log, "add", rule="b")
    accept(store, proposals, log, ["P001"])
    decline(proposals, log, ["P002"])
    with pytest.raises(RuleError, match=r"P001 \(already accepted\), P002 \(already declined\)"):
        decline(proposals, log, ["P001", "P002"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "add"},
        {"kind": "add", "rule": "a", "rule_id": "R001"},
        {"kind": "retire", "rule_id": "R001", "rule": "a"},
        {"kind": "retire", "rule_id": "R001", "scopes": ["x"]},
        {"kind": "replace", "rule": "a"},
        {"kind": "replace", "rule_id": "R999", "rule": "a"},
        {"kind": "merge", "rule": "a"},
        {"kind": "add", "rule": "a\nb"},
        {"kind": "add", "rule": "a", "decision": "I 1"},
    ],
)
def test_propose_validates(env, tmp_path, kwargs):
    store, proposals, log = env
    with pytest.raises(ValueError):
        propose(store, proposals, log, **kwargs)
    assert not (tmp_path / "proposals.json").exists()
    assert events(log, "proposed") == []


def test_report_counts_proposals(env):
    store, proposals, log = env
    decide(log, "I1", "人の答え", "none")
    decide(log, "I2", "人の答え 2", "none")
    propose(store, proposals, log, "add", rule="a", decision="I1")
    propose(store, proposals, log, "add", rule="b", decision="I1")
    propose(store, proposals, log, "retire", rule_id="R001")
    propose(store, proposals, log, "add", rule="c")
    accept(store, proposals, log, ["P001"])
    decline(proposals, log, ["P002", "P003"], reason="範囲が広すぎる")

    report = build_report(store.rules(), log.read(), pending=proposals.items)
    assert report["proposals"] == {"proposed": 4, "accepted": 1, "declined": 2, "pending": 1}
    assert report["declined_proposals"] == [
        {"proposal": "P002", "kind": "add", "rule": "b", "decision": "I1", "reason": "範囲が広すぎる"},
        {"proposal": "P003", "kind": "retire", "rule_id": "R001", "reason": "範囲が広すぎる"},
    ]
    assert [(c["decision"], c["proposals"]) for c in report["new_rule_candidates"]] == [
        ("I1", ["P001", "P002"]),
        ("I2", []),
    ]


@pytest.fixture
def k2_text(tmp_path, capsys, monkeypatch):
    def run(*args, stdin=None):
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        code = main(["--dir", str(tmp_path), *args])
        out, err = capsys.readouterr()
        return code, out, err

    return run


def test_cli_proposal_flow(k2_text, tmp_path):
    k2_text("add", "足すより引く", "--scope", "implement")
    assert k2_text("propose", "add", "-", "--decision", "I3-2", "--scope", "plan", stdin="提案は k2down に置く\n") == (0, "P001\n", "")
    assert k2_text("propose", "add", "提案は k2down に置く", "--scope", "plan") == (0, "P001\n", "")
    assert k2_text("propose", "replace", "R001", "引けるなら引く", "--source", "人の方針") == (0, "P002\n", "")
    assert k2_text("propose", "retire", "R001", "--decision", "I3-3") == (0, "P003\n", "")
    code, out, _ = k2_text("--json", "propose", "retire", "R001")
    assert json.loads(out) == {"id": "P003", "created": False}

    assert k2_text("proposals") == (0, """\
P001 add 提案は k2down に置く [scopes: plan] [decision: I3-2]
P002 replace R001 引けるなら引く [source: 人の方針]
P003 retire R001 [decision: I3-3]
""", "")
    assert k2_text("accept", "P001", "P002") == (0, "accepted P001 add R002\naccepted P002 replace R001 R003\n", "")
    assert k2_text("decline", "P003", "--reason", "置き換え済み") == (0, "declined P003\n", "")
    assert k2_text("proposals") == (0, "\n", "")
    assert k2_text("list") == (0, """\
R003 引けるなら引く [scopes: implement] [source: 人の方針]
R002 提案は k2down に置く [scopes: plan] [decision: I3-2]
""", "")
    assert k2_text("list", "--scope", "plan")[1] == "R002 提案は k2down に置く [scopes: plan] [decision: I3-2]\n"

    code, out, _ = k2_text("report")
    assert "proposals: proposed 3, accepted 2, declined 1, pending 0\n" in out
    assert "declined proposals (proposal kind target text | reason):\n  P003 retire R001 | 置き換え済み\n" in out

    code, out, err = k2_text("accept", "P001")
    assert (code, out, err) == (1, "", "error: unknown proposal id: P001 (already accepted)\n")


def test_cli_scope_command(k2_text):
    k2_text("add", "a")
    k2_text("add", "b", "--scope", "plan")
    assert k2_text("scope", "R001", "R002", "--add", "implement", "--remove", "plan") == (
        0,
        "R001 a [scopes: implement]\nR002 b [scopes: implement]\n",
        "",
    )
    code, _, err = k2_text("scope", "R001")
    assert code == 1 and "scope" in err
