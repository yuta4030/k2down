import io
import json

import pytest

from k2down.cli import main


@pytest.fixture
def k2_text(tmp_path, capsys, monkeypatch):
    def run(*args, stdin=None):
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        code = main(["--dir", str(tmp_path), *args])
        out, err = capsys.readouterr()
        return code, out, err

    return run


@pytest.fixture
def k2(k2_text):
    """--json 付きで実行し、出力を JSON として読む。"""

    def run(*args, stdin=None):
        code, out, err = k2_text("--json", *args, stdin=stdin)
        return code, (json.loads(out) if out else None), (json.loads(err) if err else None)

    return run


def read_usage(tmp_path, *skip):
    """usage.jsonl のイベントを返す。skip に挙げた種類は除く。"""
    path = tmp_path / "usage.jsonl"
    if not path.exists():
        return []
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [e for e in events if e["event"] not in skip]


def test_empty_list(k2, tmp_path):
    assert k2("list") == (0, {"rules": [], "scopes": []}, None)
    assert not (tmp_path / "rules.json").exists()


def test_add_list_apply_reject(k2, tmp_path):
    assert k2("add", "外部公開 API の認証は OAuth に統一する") == (0, {"id": "R-00001"}, None)
    assert k2("add", "-", stdin="ログは JSON で出す\n") == (0, {"id": "R-00002"}, None)

    code, out, _ = k2("list")
    assert code == 0
    assert out == {
        "rules": [
            {"id": "R-00001", "rule": "外部公開 API の認証は OAuth に統一する"},
            {"id": "R-00002", "rule": "ログは JSON で出す"},
        ],
        "scopes": [],
    }

    code, out, _ = k2("apply", "--problem", "公開 API を新設する", "R-00002", "R-00001", "R-00002")
    assert code == 0
    assert [r["id"] for r in out["applied"]] == ["R-00002", "R-00001"]

    code, out, _ = k2("reject", "--problem", "-", "R-00001", stdin="公開 API を\n新設する")
    assert code == 0
    assert out == {"rejected": [{"id": "R-00001", "rule": "外部公開 API の認証は OAuth に統一する"}]}

    assert [(u["event"], u["rule_id"], u["problem"]) for u in read_usage(tmp_path, "added")] == [
        ("applied", "R-00002", "公開 API を新設する"),
        ("applied", "R-00001", "公開 API を新設する"),
        ("rejected", "R-00001", "公開 API を 新設する"),
    ]


def test_apply_unknown_id_fails_without_logging(k2, tmp_path):
    k2("add", "a")
    code, out, err = k2("apply", "--problem", "p", "R-00001", "R-00999")
    assert code == 1 and out is None
    assert "R-00999" in err["error"]
    assert read_usage(tmp_path, "added") == []


@pytest.mark.parametrize(
    "args",
    [
        ("add", "1 行目\n2 行目"),
        ("add", "  "),
        ("add", "x", "--scope", "a b"),
        ("apply", "--problem", " ", "R-00001"),
    ],
)
def test_errors_are_json_on_stderr(k2, args):
    k2("add", "a")
    code, out, err = k2(*args)
    assert code == 1 and out is None and "error" in err


def test_v1_tree_is_read_as_flat_list(k2, tmp_path):
    data = {"version": 1, "issued": {"N": 1, "R": 4}, "root": {"id": "N000", "summary": "全体", "children": [
        {"id": "N001", "summary": "認証", "children": [{"id": "R001", "rule": "a"}]},
        {"id": "R002", "rule": "b"},
    ]}}
    (tmp_path / "rules.json").write_text(json.dumps(data), encoding="utf-8")
    assert [r["id"] for r in k2("list")[1]["rules"]] == ["R001", "R002"]
    assert k2("add", "c")[1] == {"id": "R-00001"}
    assert k2("apply", "--problem", "p", "R001", "R-00001")[0] == 0
    saved = json.loads((tmp_path / "rules.json").read_text(encoding="utf-8"))
    assert saved == {"version": 2, "rules": [
        {"id": "R001", "rule": "a"}, {"id": "R002", "rule": "b"}, {"id": "R-00001", "rule": "c"},
    ]}


def test_retired_ids_are_not_reissued(k2, monkeypatch):
    k2("add", "a")
    k2("retire", "R-00001")
    ids = iter(["R-00001", "R-00002"])  # 1 つ目は消したルールの ID と同じ
    monkeypatch.setattr("k2down.core.model.random_id", lambda prefix: next(ids))
    assert k2("add", "b")[1] == {"id": "R-00002"}


def test_corrupt_rules_json(k2, tmp_path):
    (tmp_path / "rules.json").write_text("{", encoding="utf-8")
    code, _, err = k2("list")
    assert code == 1 and "error" in err


def test_k2down_dir_env(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("K2DOWN_DIR", str(tmp_path))
    assert main(["add", "a"]) == 0
    assert (tmp_path / "rules.json").exists()


def test_text_list(k2_text, tmp_path):
    k2_text("add", "外部公開 API の認証は OAuth に統一する", "--scope", "plan", "--scope", "implement")
    k2_text("add", "ログは JSON で出す", "--decision", "I1-4", "--source", "人の方針")
    assert k2_text("list") == (0, """\
R-00001 外部公開 API の認証は OAuth に統一する [scopes: implement plan]
R-00002 ログは JSON で出す [decision: I1-4] [source: 人の方針]
""", "")


def test_text_empty_list(k2_text):
    assert k2_text("list") == (0, "\n", "")


def test_text_add_apply_reject(k2_text, tmp_path):
    assert k2_text("add", "a") == (0, "R-00001\n", "")
    assert k2_text("add", "b") == (0, "R-00002\n", "")
    assert k2_text("apply", "--problem", "p", "R-00002", "R-00001") == (0, "applied R-00002 R-00001\n", "")
    assert k2_text("reject", "--problem", "p", "R-00001") == (0, "rejected R-00001\n", "")
    assert len(read_usage(tmp_path, "added")) == 3


def test_text_error(k2_text, tmp_path):
    k2_text("add", "a")
    code, out, err = k2_text("apply", "--problem", "p", "R-00999")
    assert (code, out, err) == (1, "", "error: unknown rule id: R-00999\n")
    assert read_usage(tmp_path, "added") == []


@pytest.mark.parametrize("position", ["before", "after"])
def test_json_flag_position(k2_text, position):
    args = ["--json", "add", "a"] if position == "before" else ["add", "a", "--json"]
    code, out, _ = k2_text(*args)
    assert code == 0 and json.loads(out) == {"id": "R-00001"}


def test_decision_flow(k2, tmp_path):
    k2("add", "足すより引く", "--source", "session abc")
    k2("add", "区別すべきは区別する")
    assert k2("apply", "--decision", "D1", "--problem", "p", "R-00001", "R-00002")[0] == 0
    code, out, _ = k2("decide", "--decision", "D1", "--predicted", "引く", "--actual", "-", "--outcome", "miss", stdin="足す\n")
    assert code == 0
    assert out == {"decided": {"decision": "D1", "predicted": "引く", "actual": "足す", "outcome": "miss"}}
    assert k2("escalate", "--decision", "D2", "--problem", "q", "--reason", "conflict", "R-00002", "R-00001") == (
        0,
        {"escalated": {"decision": "D2", "reason": "conflict", "rule_ids": ["R-00002", "R-00001"]}},
        None,
    )
    events = read_usage(tmp_path, "added")
    assert [e["event"] for e in events] == ["applied", "applied", "decided", "escalated"]
    assert events[0]["decision"] == "D1"

    code, out, _ = k2("report")
    assert code == 0
    assert out["conflict_candidates"] == [{"rule_ids": ["R-00001", "R-00002"], "decisions": ["D1", "D2"]}]
    assert k2("list")[1]["rules"][0]["source"] == "session abc"


def test_replace_and_retire(k2, tmp_path):
    for text in "abc":
        k2("add", text)
    assert k2("replace", "R-00001", "a2") == (0, {"rule_id": "R-00001", "replaced_by": "R-00004"}, None)
    assert k2("retire", "R-00003")[1] == {"retired": [{"id": "R-00003", "rule": "c"}]}
    assert k2("add", "d")[1] == {"id": "R-00005"}
    assert [r["id"] for r in k2("list")[1]["rules"]] == ["R-00004", "R-00002", "R-00005"]
    code, _, err = k2("apply", "--problem", "p", "R-00001")
    assert code == 1 and err == {"error": "unknown rule id: R-00001 (replaced by R-00004)"}
    assert [(e["event"], e["rule_id"]) for e in read_usage(tmp_path, "added")] == [("replaced", "R-00001"), ("retired", "R-00003")]


def test_text_new_commands(k2_text, tmp_path):
    k2_text("add", "a", "--source", "D0")
    k2_text("add", "b")
    assert k2_text("list")[1] == "R-00001 a [source: D0]\nR-00002 b\n"
    assert k2_text("apply", "--decision", "D1", "--problem", "p", "R-00001") == (0, "applied R-00001\n", "")
    assert k2_text("decide", "--decision", "D1", "--actual", "x", "--outcome", "hit") == (0, "decided D1 hit\n", "")
    assert k2_text("escalate", "--decision", "D2", "--problem", "q", "--reason", "no_match") == (0, "escalated D2 no_match\n", "")
    assert k2_text("decide", "--decision", "D2", "--actual", "人が決めた", "--outcome", "none") == (0, "decided D2 none\n", "")
    assert k2_text("replace", "R-00002", "b2") == (0, "R-00003\n", "")
    assert k2_text("retire", "R-00003") == (0, "retired R-00003\n", "")

    code, out, _ = k2_text("report")
    assert code == 0
    assert "decisions 2: hit 1, miss 0, none 1\n" in out
    assert "rules (ID applied hit miss rejected decisions-since-added text):\n  R-00001 1 1 0 0 2 a\n" in out
    assert "drop candidates (never applied in 10+ decisions since added; ID decisions text):\n  (none)\n" in out
    assert "new rule candidates (decided with outcome none):\n  D2 problem: q | actual: 人が決めた\n" in out


@pytest.mark.parametrize(
    "args",
    [
        ("apply", "--decision", "D 1", "--problem", "p", "R-00001"),
        ("escalate", "--decision", "D1", "--problem", "p", "--reason", "conflict", "R-00001"),
        ("escalate", "--decision", "D1", "--problem", "p", "--reason", "conflict", "R-00001", "R-00999"),
        ("replace", "R-00999", "x"),
        ("retire", "R-00001", "R-00999"),
        ("report", "--since", "yesterday"),
    ],
)
def test_new_command_errors(k2, tmp_path, args):
    k2("add", "a")
    k2("add", "b")
    code, out, err = k2(*args)
    assert code == 1 and out is None and "error" in err
    assert read_usage(tmp_path, "added") == []
    assert len(k2("list")[1]["rules"]) == 2
