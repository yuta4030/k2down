"""利用者との約束（README「互換性」）を守っているかのテスト。

ここが落ちる変更は、利用者の連携を壊す。直すならマイナー版を上げ、CHANGELOG の「壊れる変更」に書く。
キーは「最低限あること」を見る。キーを足すのは壊れる変更ではない（利用者は知らないキーを無視する）。
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

import k2down
from k2down.cli import main

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def k2(tmp_path, capsys):
    def run(*args):
        code = main(["--dir", str(tmp_path), "--json", *args])
        out, err = capsys.readouterr()
        return code, (json.loads(out) if out else None), (json.loads(err) if err else None)

    return run


def has_keys(data, *keys):
    missing = set(keys) - set(data)
    assert not missing, f"missing keys {missing} in {data}"


def test_version_output(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert re.fullmatch(r"k2down \d+\.\d+\.\d+\n", out)
    assert out.split()[-1] == k2down.__version__


def test_version_matches_pyproject():
    with (ROOT / "pyproject.toml").open("rb") as f:
        assert tomllib.load(f)["project"]["version"] == k2down.__version__


def test_rule_commands(k2):
    code, out, _ = k2("add", "a", "--scope", "plan", "--decision", "D1", "--source", "s")
    assert code == 0
    has_keys(out, "id")
    first = out["id"]

    code, out, _ = k2("list")
    has_keys(out, "rules", "scopes")
    has_keys(out["rules"][0], "id", "rule", "scopes", "decision", "source")

    code, out, _ = k2("scope", first, "--add", "implement")
    has_keys(out, "rules")
    has_keys(out["rules"][0], "id", "rule", "scopes")

    code, out, _ = k2("replace", first, "a2")
    has_keys(out, "rule_id", "replaced_by")
    second = out["replaced_by"]

    code, out, _ = k2("retire", second)
    has_keys(out, "retired")
    has_keys(out["retired"][0], "id", "rule")


def test_record_commands(k2):
    rule_id = k2("add", "a")[1]["id"]
    rule_b = k2("add", "b")[1]["id"]
    for command, event in (("apply", "applied"), ("reject", "rejected")):
        code, out, _ = k2(command, "--decision", "D1", "--problem", "p", rule_id)
        has_keys(out, event)
        has_keys(out[event][0], "id", "rule")

    code, out, _ = k2("decide", "--decision", "D1", "--actual", "x", "--outcome", "miss", "--predicted", "y")
    has_keys(out, "decided")
    has_keys(out["decided"], "decision", "actual", "outcome", "predicted")

    code, out, _ = k2("escalate", "--decision", "D2", "--problem", "p", "--reason", "conflict", rule_id, rule_b)
    has_keys(out, "escalated")
    has_keys(out["escalated"], "decision", "reason", "rule_ids")


def test_proposal_commands(k2):
    rule_id = k2("add", "a")[1]["id"]

    code, out, _ = k2("propose", "add", "b", "--decision", "D1", "--source", "s", "--scope", "plan")
    has_keys(out, "id", "created")
    added = out["id"]
    retired = k2("propose", "retire", rule_id, "--decision", "D2")[1]["id"]
    declined = k2("propose", "add", "c")[1]["id"]

    code, out, _ = k2("proposals")
    has_keys(out, "proposals")
    by_id = {p["id"]: p for p in out["proposals"]}
    has_keys(by_id[added], "id", "kind", "rule", "decision", "source", "scopes")
    has_keys(by_id[retired], "id", "kind", "rule_id", "decision")

    code, out, _ = k2("accept", added, retired)
    has_keys(out, "accepted")
    for item in out["accepted"]:
        has_keys(item, "proposal", "kind", "rule_id")

    code, out, _ = k2("decline", declined)
    has_keys(out, "declined")
    has_keys(out["declined"][0], "id", "kind")


def test_report(k2):
    a = k2("add", "a")[1]["id"]
    b = k2("add", "b")[1]["id"]
    k2("apply", "--decision", "D1", "--problem", "p", a, b)
    k2("decide", "--decision", "D1", "--actual", "x", "--outcome", "miss")
    k2("decide", "--decision", "D2", "--actual", "y", "--outcome", "none")
    k2("decline", k2("propose", "add", "c", "--decision", "D2")[1]["id"])

    code, out, _ = k2("report", "--min-decisions", "0")
    has_keys(
        out,
        "since",
        "decisions",
        "rules",
        "min_decisions",
        "drop_candidates",
        "rewrite_candidates",
        "conflict_candidates",
        "new_rule_candidates",
        "proposals",
        "declined_proposals",
        "daily",
    )
    has_keys(out["decisions"], "decided", "hit", "miss", "none")
    has_keys(out["rules"][0], "id", "rule", "applied", "hit", "miss", "rejected", "decisions")
    has_keys(out["conflict_candidates"][0], "rule_ids", "decisions")
    has_keys(out["new_rule_candidates"][0], "decision", "problem", "actual", "proposals")
    has_keys(out["proposals"], "proposed", "accepted", "declined", "pending")
    has_keys(out["declined_proposals"][0], "proposal", "kind", "rule", "decision")
    has_keys(out["daily"][0], "date", "decided", "hit", "ratio")
    assert isinstance(out["drop_candidates"], list) and isinstance(out["rewrite_candidates"], list)


@pytest.mark.parametrize(
    "args",
    [
        ("apply", "--problem", "p", "R-zzzzz"),  # 実行時の誤り
        ("nosuch",),  # 引数の誤り
        ("apply", "R-zzzzz"),  # 必須の引数がない
    ],
)
def test_errors_exit_1_with_json_on_stderr(k2, args):
    code, out, err = k2(*args)
    assert (code, out) == (1, None)
    has_keys(err, "error")


def test_text_errors_exit_1(tmp_path, capsys):
    assert main(["--dir", str(tmp_path), "nosuch"]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_newer_file_asks_to_upgrade(k2, tmp_path):
    (tmp_path / "rules.json").write_text('{"version": 99, "rules": []}', encoding="utf-8")
    code, _, err = k2("list")
    assert code == 1 and "upgrade k2down" in err["error"]
