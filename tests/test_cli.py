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


def read_usage(tmp_path):
    return [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()]


def test_empty_list(k2, tmp_path):
    assert k2("list") == (0, {"rules": []}, None)
    assert not (tmp_path / "rules.json").exists()


def test_add_list_apply_reject(k2, tmp_path):
    assert k2("add", "外部公開 API の認証は OAuth に統一する") == (0, {"id": "R001"}, None)
    assert k2("add", "-", stdin="ログは JSON で出す\n") == (0, {"id": "R002"}, None)

    code, out, _ = k2("list")
    assert code == 0
    assert out == {
        "rules": [
            {"id": "R001", "rule": "外部公開 API の認証は OAuth に統一する", "parent": "N000"},
            {"id": "R002", "rule": "ログは JSON で出す", "parent": "N000"},
        ]
    }

    code, out, _ = k2("apply", "--problem", "公開 API を新設する", "R002", "R001", "R002")
    assert code == 0
    assert [r["id"] for r in out["applied"]] == ["R002", "R001"]

    code, out, _ = k2("reject", "--problem", "-", "R001", stdin="公開 API を\n新設する")
    assert code == 0
    assert out == {"rejected": [{"id": "R001", "rule": "外部公開 API の認証は OAuth に統一する"}]}

    assert [(u["event"], u["rule_id"], u["problem"]) for u in read_usage(tmp_path)] == [
        ("applied", "R002", "公開 API を新設する"),
        ("applied", "R001", "公開 API を新設する"),
        ("rejected", "R001", "公開 API を 新設する"),
    ]


def test_apply_unknown_id_fails_without_logging(k2, tmp_path):
    k2("add", "a")
    code, out, err = k2("apply", "--problem", "p", "R001", "R999")
    assert code == 1 and out is None
    assert "R999" in err["error"]
    assert not (tmp_path / "usage.jsonl").exists()


@pytest.mark.parametrize(
    "args",
    [
        ("add", "1 行目\n2 行目"),
        ("add", "  "),
        ("add", "x", "--parent", "N999"),
        ("apply", "--problem", " ", "R001"),
    ],
)
def test_errors_are_json_on_stderr(k2, args):
    k2("add", "a")
    code, out, err = k2(*args)
    assert code == 1 and out is None and "error" in err


def test_add_under_nested_parent(k2, tmp_path):
    data = {"version": 1, "root": {"id": "N000", "summary": "全体", "children": [
        {"id": "N001", "summary": "認証", "children": [{"id": "R001", "rule": "a"}]},
        {"id": "R002", "rule": "b"},
    ]}}
    (tmp_path / "rules.json").write_text(json.dumps(data), encoding="utf-8")
    assert k2("add", "c", "--parent", "N001")[1] == {"id": "R003"}
    assert [(r["id"], r["parent"]) for r in k2("list")[1]["rules"]] == [("R001", "N001"), ("R003", "N001"), ("R002", "N000")]


def test_corrupt_rules_json(k2, tmp_path):
    (tmp_path / "rules.json").write_text("{", encoding="utf-8")
    code, _, err = k2("list")
    assert code == 1 and "error" in err


def test_k2down_dir_env(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("K2DOWN_DIR", str(tmp_path))
    assert main(["add", "a"]) == 0
    assert (tmp_path / "rules.json").exists()


NESTED = {"version": 1, "root": {"id": "N000", "summary": "全体", "children": [
    {"id": "R001", "rule": "外部公開 API の認証は OAuth に統一する"},
    {"id": "N001", "summary": "社内\n認証", "children": [
        {"id": "R002", "rule": "社内バッチ間の認証はサービスアカウントで行う", "note": "notes/R002.md"},
    ]},
    {"id": "R003", "rule": "ログは JSON で出す"},
]}}


def test_text_list_is_indented_tree(k2_text, tmp_path):
    (tmp_path / "rules.json").write_text(json.dumps(NESTED), encoding="utf-8")
    assert k2_text("list") == (0, """\
N000 全体
  R001 外部公開 API の認証は OAuth に統一する
  N001 社内 認証
    R002 社内バッチ間の認証はサービスアカウントで行う [note: notes/R002.md]
  R003 ログは JSON で出す
""", "")


def test_text_empty_list(k2_text):
    assert k2_text("list") == (0, "N000 全体\n", "")


def test_text_add_apply_reject(k2_text, tmp_path):
    assert k2_text("add", "a") == (0, "R001\n", "")
    assert k2_text("add", "b") == (0, "R002\n", "")
    assert k2_text("apply", "--problem", "p", "R002", "R001") == (0, "applied R002 R001\n", "")
    assert k2_text("reject", "--problem", "p", "R001") == (0, "rejected R001\n", "")
    assert len(read_usage(tmp_path)) == 3


def test_text_error(k2_text, tmp_path):
    k2_text("add", "a")
    code, out, err = k2_text("apply", "--problem", "p", "R999")
    assert (code, out, err) == (1, "", "error: unknown rule id: R999\n")
    assert not (tmp_path / "usage.jsonl").exists()


@pytest.mark.parametrize("position", ["before", "after"])
def test_json_flag_position(k2_text, position):
    args = ["--json", "add", "a"] if position == "before" else ["add", "a", "--json"]
    code, out, _ = k2_text(*args)
    assert code == 0 and json.loads(out) == {"id": "R001"}
