import json

import pytest

from k2down.core import RuleError, RuleStore

SAMPLE = {
    "version": 1,
    "root": {
        "id": "N000",
        "summary": "全体",
        "children": [
            {"id": "R001", "rule": "外部公開 API の認証は OAuth に統一する"},
            {"id": "R002", "rule": "社内バッチ間の認証はサービスアカウントで行う", "note": "notes/R002.md"},
        ],
    },
}


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_missing_file_is_empty_tree(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    assert store.rules() == []
    assert not (tmp_path / "rules.json").exists()


def test_load_sample(tmp_path):
    write(tmp_path / "rules.json", SAMPLE)
    rules = RuleStore(tmp_path / "rules.json").rules()
    assert [r.id for r in rules] == ["R001", "R002"]
    assert rules[1].note == "notes/R002.md"


def test_add_rule_creates_file_and_numbers_ids(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    assert store.add_rule("ログは JSON で出す").id == "R001"
    assert store.add_rule("  時刻は UTC で保存する  ").id == "R002"
    reloaded = RuleStore(tmp_path / "rules.json")
    assert [(r.id, r.rule) for r in reloaded.rules()] == [("R001", "ログは JSON で出す"), ("R002", "時刻は UTC で保存する")]


def test_add_rule_continues_after_max_id(tmp_path):
    data = json.loads(json.dumps(SAMPLE))
    data["root"]["children"] = [{"id": "R007", "rule": "a"}]
    write(tmp_path / "rules.json", data)
    assert RuleStore(tmp_path / "rules.json").add_rule("b").id == "R008"


def test_add_rule_under_parent(tmp_path):
    data = json.loads(json.dumps(SAMPLE))
    data["root"]["children"].append({"id": "N001", "summary": "認証", "children": []})
    write(tmp_path / "rules.json", data)
    store = RuleStore(tmp_path / "rules.json")
    rule = store.add_rule("管理画面は SSO 必須", parent_id="N001")
    assert rule.id == "R003"
    assert RuleStore(tmp_path / "rules.json").get("N001").children[0].id == "R003"


@pytest.mark.parametrize("parent_id", ["N999", "R001"])
def test_add_rule_rejects_bad_parent(tmp_path, parent_id):
    write(tmp_path / "rules.json", SAMPLE)
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").add_rule("x", parent_id=parent_id)


@pytest.mark.parametrize("text", ["", "   ", "1 行目\n2 行目", "a\rb"])
def test_add_rule_rejects_invalid_text(tmp_path, text):
    store = RuleStore(tmp_path / "rules.json")
    with pytest.raises(RuleError):
        store.add_rule(text)
    assert not (tmp_path / "rules.json").exists()


def test_save_format_is_stable(tmp_path):
    write(tmp_path / "rules.json", SAMPLE)
    store = RuleStore(tmp_path / "rules.json")
    store.save()
    text = (tmp_path / "rules.json").read_text(encoding="utf-8")
    expected = json.dumps(SAMPLE, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert text == expected
    assert '"rule": "外部公開' in text  # 日本語をエスケープしない
    store.save()
    assert (tmp_path / "rules.json").read_text(encoding="utf-8") == expected


def test_rejects_duplicate_ids(tmp_path):
    data = json.loads(json.dumps(SAMPLE))
    data["root"]["children"][1]["id"] = "R001"
    write(tmp_path / "rules.json", data)
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json")


def test_rejects_unknown_version(tmp_path):
    write(tmp_path / "rules.json", {**SAMPLE, "version": 2})
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json")
