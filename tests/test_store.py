import json
import re

import pytest

from k2down.core import RuleError, RuleStore

SAMPLE = {
    "version": 2,
    "rules": [
        {"id": "R-00001", "rule": "外部公開 API の認証は OAuth に統一する", "scopes": ["implement"]},
        {"id": "R-00002", "rule": "社内バッチ間の認証はサービスアカウントで行う", "note": "notes/R-00002.md", "decision": "I1-4"},
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
    assert [r.id for r in rules] == ["R-00001", "R-00002"]
    assert rules[1].note == "notes/R-00002.md"
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
    assert store.add_rule("ログは JSON で出す").id == "R-00001"
    assert store.add_rule("  時刻は UTC で保存する  ").id == "R-00002"
    reloaded = RuleStore(tmp_path / "rules.json")
    assert [(r.id, r.rule) for r in reloaded.rules()] == [("R-00001", "ログは JSON で出す"), ("R-00002", "時刻は UTC で保存する")]


def test_new_ids_avoid_existing_and_taken(tmp_path):
    write(tmp_path / "rules.json", {"version": 2, "rules": [{"id": "R-00001", "rule": "a"}]})
    assert RuleStore(tmp_path / "rules.json").add_rule("b", taken={"R-00002"}).id == "R-00003"


def test_real_ids_are_random(tmp_path, monkeypatch):
    monkeypatch.undo()  # テスト用の連番をやめ、本物の random_id を使う
    store = RuleStore(tmp_path / "rules.json")
    ids = {store.add_rule(str(n)).id for n in range(20)}
    assert len(ids) == 20
    assert all(re.fullmatch(r"R-[0-9a-hjkmnp-tv-z]{5}", rule_id) for rule_id in ids)


def test_add_rule_with_scopes(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    store.add_rule("a", scopes=["review", "implement", "review"])
    store.add_rule("b")
    store.add_rule("c", scopes=["plan"])
    reloaded = RuleStore(tmp_path / "rules.json")
    assert reloaded.rules()[0].scopes == ["implement", "review"]
    assert reloaded.scopes() == ["implement", "plan", "review"]
    assert [r.id for r in reloaded.rules(["implement"])] == ["R-00001", "R-00002"]
    assert [r.id for r in reloaded.rules(["plan", "review"])] == ["R-00001", "R-00002", "R-00003"]
    assert [r.id for r in reloaded.rules(["other"])] == ["R-00002"]


@pytest.mark.parametrize("scopes", [["a b"], [""], "implement"])
def test_add_rule_rejects_bad_scopes(tmp_path, scopes):
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").add_rule("x", scopes=scopes)
    assert not (tmp_path / "rules.json").exists()


def test_change_scopes_keeps_ids(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    store.add_rule("a", scopes=["plan"])
    store.add_rule("b")
    store.change_scopes(["R-00001", "R-00002"], add=["implement"], remove=["plan"])
    assert [(r.id, r.scopes) for r in RuleStore(tmp_path / "rules.json").rules()] == [
        ("R-00001", ["implement"]),
        ("R-00002", ["implement"]),
    ]
    with pytest.raises(RuleError):
        store.change_scopes(["R-00001"], add=[], remove=[])
    with pytest.raises(RuleError):
        store.change_scopes(["R-00001", "R-00999"], add=["x"], remove=[])
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
    data["rules"][1]["id"] = "R-00001"
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
    assert [r.id for r in store.retire_rules(["R-00003", "R-00002"])] == ["R-00003", "R-00002"]
    reloaded = RuleStore(tmp_path / "rules.json")
    assert [r.id for r in reloaded.rules()] == ["R-00001"]
    assert reloaded.add_rule("d").id == "R-00004"


def test_legacy_ids_stay_valid(tmp_path):
    write(tmp_path / "rules.json", V1)
    store = RuleStore(tmp_path / "rules.json")
    store.retire_rules(["R002"])
    store.add_rule("x")
    assert [r.id for r in RuleStore(tmp_path / "rules.json").rules()] == ["R001", "R-00001"]


def test_retire_unknown_changes_nothing(tmp_path):
    write(tmp_path / "rules.json", SAMPLE)
    before = (tmp_path / "rules.json").read_text(encoding="utf-8")
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").retire_rules(["R-00001", "R-00999"])
    assert (tmp_path / "rules.json").read_text(encoding="utf-8") == before


def test_replace_keeps_position_and_scopes_with_new_id(tmp_path):
    data = json.loads(json.dumps(SAMPLE))
    data["rules"].insert(0, {"id": "R005", "rule": "a"})
    write(tmp_path / "rules.json", data)
    store = RuleStore(tmp_path / "rules.json")
    old, new = store.replace_rule("R-00001", "外部公開 API の認証は OIDC に統一する", decision="D9")
    assert (old.id, new.id, new.decision, new.scopes) == ("R-00001", "R-00003", "D9", ["implement"])
    _, newer = store.replace_rule("R-00003", "x", scopes=["plan"])
    assert newer.scopes == ["plan"]
    reloaded = RuleStore(tmp_path / "rules.json")
    assert [r.id for r in reloaded.rules()] == ["R005", "R-00004", "R-00002"]
    assert reloaded.get("R-00001") is None


def test_replace_unknown_or_invalid_changes_nothing(tmp_path):
    write(tmp_path / "rules.json", SAMPLE)
    before = (tmp_path / "rules.json").read_text(encoding="utf-8")
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").replace_rule("R-00999", "x")
    with pytest.raises(RuleError):
        RuleStore(tmp_path / "rules.json").replace_rule("R-00001", "a\nb")
    assert (tmp_path / "rules.json").read_text(encoding="utf-8") == before
