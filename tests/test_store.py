import json

import pytest

from k2down.core import RuleError, RuleStore

SAMPLE = {
    "version": 2,
    "rules": [
        {"id": "R001", "rule": "外部公開 API の認証は OAuth に統一する", "scopes": ["implement"]},
        {"id": "R002", "rule": "社内バッチ間の認証はサービスアカウントで行う", "note": "notes/R002.md", "decision": "I1-4"},
    ],
}

V1 = {
    "version": 1,
    "root": {
        "id": "N000",
        "summary": "全体",
        "children": [
            {"id": "R001", "rule": "a"},
            {"id": "N001", "summary": "認証", "children": [{"id": "R002", "rule": "b", "source": "x"}]},
        ],
    },
}


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_missing_file_is_empty(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    assert store.rules() == []
    assert not (tmp_path / "rules.json").exists()


def test_load_sample(tmp_path):
    write(tmp_path / "rules.json", SAMPLE)
    rules = RuleStore(tmp_path / "rules.json").rules()
    assert [r.id for r in rules] == ["R001", "R002"]
    assert rules[1].note == "notes/R002.md"
    assert (rules[0].scopes, rules[1].decision) == (["implement"], "I1-4")


def test_load_v1_tree_as_flat_list(tmp_path):
    write(tmp_path / "rules.json", V1)
    store = RuleStore(tmp_path / "rules.json")
    assert [(r.id, r.rule, r.source) for r in store.rules()] == [("R001", "a", None), ("R002", "b", "x")]
    store.save()
    assert json.loads((tmp_path / "rules.json").read_text(encoding="utf-8")) == {
        "version": 2,
        "rules": [{"id": "R001", "rule": "a"}, {"id": "R002", "rule": "b", "source": "x"}],
    }


def test_add_rule_creates_file_and_numbers_ids(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    assert store.add_rule("ログは JSON で出す").id == "R001"
    assert store.add_rule("  時刻は UTC で保存する  ").id == "R002"
    reloaded = RuleStore(tmp_path / "rules.json")
    assert [(r.id, r.rule) for r in reloaded.rules()] == [("R001", "ログは JSON で出す"), ("R002", "時刻は UTC で保存する")]


def test_add_rule_continues_after_max_id(tmp_path):
    data = {"version": 2, "rules": [{"id": "R007", "rule": "a"}]}
    write(tmp_path / "rules.json", data)
    assert RuleStore(tmp_path / "rules.json").add_rule("b").id == "R008"


def test_add_rule_with_scopes(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    store.add_rule("a", scopes=["review", "implement", "review"])
    store.add_rule("b")
    store.add_rule("c", scopes=["plan"])
    reloaded = RuleStore(tmp_path / "rules.json")
    assert reloaded.rules()[0].scopes == ["implement", "review"]
    assert reloaded.scopes() == ["implement", "plan", "review"]
    assert [r.id for r in reloaded.rules(["implement"])] == ["R001", "R002"]
    assert [r.id for r in reloaded.rules(["plan", "review"])] == ["R001", "R002", "R003"]
    assert [r.id for r in reloaded.rules(["other"])] == ["R002"]


@pytest.mark.parametrize("scopes", [["a b"], [""], "implement"])
def test_add_rule_rejects_bad_scopes(tmp_path, scopes):
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").add_rule("x", scopes=scopes)
    assert not (tmp_path / "rules.json").exists()


def test_change_scopes_keeps_ids(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    store.add_rule("a", scopes=["plan"])
    store.add_rule("b")
    store.change_scopes(["R001", "R002"], add=["implement"], remove=["plan"])
    assert [(r.id, r.scopes) for r in RuleStore(tmp_path / "rules.json").rules()] == [
        ("R001", ["implement"]),
        ("R002", ["implement"]),
    ]
    with pytest.raises(RuleError):
        store.change_scopes(["R001"], add=[], remove=[])
    with pytest.raises(RuleError):
        store.change_scopes(["R001", "R999"], add=["x"], remove=[])
    assert RuleStore(tmp_path / "rules.json").rules()[0].scopes == ["implement"]


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
    data["rules"][1]["id"] = "R001"
    write(tmp_path / "rules.json", data)
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json")


def test_rejects_unknown_version(tmp_path):
    write(tmp_path / "rules.json", {**SAMPLE, "version": 3})
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json")


def test_add_rule_with_source(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    store.add_rule("足すより引く", source="session abc")
    assert RuleStore(tmp_path / "rules.json").rules()[0].source == "session abc"
    with pytest.raises(RuleError):
        store.add_rule("x", source="1 行目\n2 行目")


def test_retire_never_reuses_ids(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    for text in "abc":
        store.add_rule(text)
    assert [r.id for r in store.retire_rules(["R003", "R002"])] == ["R003", "R002"]
    reloaded = RuleStore(tmp_path / "rules.json")
    assert [r.id for r in reloaded.rules()] == ["R001"]
    assert reloaded.add_rule("d").id == "R004"


def test_retire_v01_file_without_issued(tmp_path):
    write(tmp_path / "rules.json", V1)
    store = RuleStore(tmp_path / "rules.json")
    store.retire_rules(["R002"])
    assert json.loads((tmp_path / "rules.json").read_text(encoding="utf-8"))["issued"] == {"R": 2}
    assert RuleStore(tmp_path / "rules.json").add_rule("x").id == "R003"


def test_retire_unknown_changes_nothing(tmp_path):
    write(tmp_path / "rules.json", SAMPLE)
    before = (tmp_path / "rules.json").read_text(encoding="utf-8")
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").retire_rules(["R001", "R999"])
    assert (tmp_path / "rules.json").read_text(encoding="utf-8") == before


def test_replace_keeps_position_and_scopes_with_new_id(tmp_path):
    data = json.loads(json.dumps(SAMPLE))
    data["rules"].insert(0, {"id": "R005", "rule": "a"})
    write(tmp_path / "rules.json", data)
    store = RuleStore(tmp_path / "rules.json")
    old, new = store.replace_rule("R001", "外部公開 API の認証は OIDC に統一する", decision="D9")
    assert (old.id, new.id, new.decision, new.scopes) == ("R001", "R006", "D9", ["implement"])
    _, newer = store.replace_rule("R006", "x", scopes=["plan"])
    assert newer.scopes == ["plan"]
    reloaded = RuleStore(tmp_path / "rules.json")
    assert [r.id for r in reloaded.rules()] == ["R005", "R007", "R002"]
    assert reloaded.get("R001") is None


def test_replace_unknown_or_invalid_changes_nothing(tmp_path):
    write(tmp_path / "rules.json", SAMPLE)
    before = (tmp_path / "rules.json").read_text(encoding="utf-8")
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").replace_rule("R999", "x")
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").replace_rule("R001", "a\nb")
    assert (tmp_path / "rules.json").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("issued", [[], {"X": 1}, {"N": 1}, {"R": -1}, {"R": "3"}, {"R": True}])
def test_rejects_invalid_issued(tmp_path, issued):
    write(tmp_path / "rules.json", {**SAMPLE, "issued": issued})
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json")
