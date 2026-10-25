import json
from datetime import date, datetime, timedelta, timezone

import pytest

from k2down.core import RuleError, RuleStore, UsageLog, add, build_report, decide, escalate, record, replace, retire

JST = timezone(timedelta(hours=9))


@pytest.fixture
def env(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    for text in ("足すより引く", "区別すべきは区別する", "ログは JSON で出す", "使われない"):
        store.add_rule(text)
    return store, UsageLog(tmp_path / "usage.jsonl")


def test_report_counts_and_candidates(env):
    store, log = env
    record(store, log, "applied", ["R001", "R002"], "設定を足すか", decision="D1")
    decide(log, "D1", "足す", "miss", predicted="引く")
    record(store, log, "applied", ["R003"], "ログ形式", decision="D2")
    decide(log, "D2", "JSON", "hit")
    record(store, log, "rejected", ["R003"], "別の件")
    escalate(store, log, "D3", "新しい話", "no_match")
    decide(log, "D3", "人が決めた", "none")
    escalate(store, log, "D4", "ぶつかった", "conflict", ["R002", "R001"])

    report = build_report(store.rules(), log.read(), min_decisions=3)
    assert report["decisions"] == {"decided": 3, "hit": 1, "miss": 1, "none": 1}
    assert [(r["id"], r["applied"], r["hit"], r["miss"], r["rejected"]) for r in report["rules"]] == [
        ("R001", 1, 0, 1, 0),
        ("R002", 1, 0, 1, 0),
        ("R003", 1, 1, 0, 1),
        ("R004", 0, 0, 0, 0),
    ]
    assert report["drop_candidates"] == ["R004"]
    assert report["rewrite_candidates"] == ["R001", "R002", "R003"]
    assert report["conflict_candidates"] == [{"rule_ids": ["R001", "R002"], "decisions": ["D1", "D4"]}]
    assert report["new_rule_candidates"] == [
        {"decision": "D3", "problem": "新しい話", "actual": "人が決めた", "proposals": []}
    ]
    [day] = report["daily"]
    assert (day["decided"], day["hit"], day["ratio"]) == (3, 1, 0.33)


def test_drop_candidates_wait_for_decisions_since_added(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    log = UsageLog(tmp_path / "usage.jsonl")
    store.add_rule("足した記録のない古いルール")
    log.write("decided", ts=datetime(2026, 10, 1, 9, tzinfo=JST), decision="D1", actual="x", outcome="none")
    add(store, log, "足したばかりのルール")  # 今の時刻で added が記録される
    log.write("decided", ts=datetime(2026, 10, 1, 10, tzinfo=timezone.utc), decision="D2", actual="x", outcome="none")

    report = build_report(store.rules(), log.read(), min_decisions=2)
    assert [(r["id"], r["decisions"]) for r in report["rules"]] == [("R001", 2), ("R002", 0)]
    assert report["drop_candidates"] == ["R001"]
    assert build_report(store.rules(), log.read(), min_decisions=3)["drop_candidates"] == []
    with pytest.raises(ValueError):
        build_report(store.rules(), log.read(), min_decisions=-1)


def test_replacement_counts_from_when_it_was_replaced(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    log = UsageLog(tmp_path / "usage.jsonl")
    store.add_rule("a")
    log.write("decided", ts=datetime(2026, 10, 1, tzinfo=JST), decision="D1", actual="x", outcome="none")
    replace(store, log, "R001", "a2")
    assert build_report(store.rules(), log.read(), min_decisions=1)["drop_candidates"] == []


def test_last_decided_wins(env):
    store, log = env
    record(store, log, "applied", ["R001"], "p", decision="D1")
    decide(log, "D1", "x", "miss")
    decide(log, "D1", "x", "hit")
    report = build_report(store.rules(), log.read())
    assert report["decisions"] == {"decided": 1, "hit": 1, "miss": 0, "none": 0}
    assert (report["rules"][0]["hit"], report["rules"][0]["miss"]) == (1, 0)


def test_since_and_daily_ratio(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    store.add_rule("a")
    log = UsageLog(tmp_path / "usage.jsonl")
    for day, outcome in ((15, "hit"), (16, "hit"), (16, "miss")):
        ts = datetime(2026, 10, day, 9, tzinfo=JST)
        log.write("decided", ts=ts, decision=f"D{day}{outcome}", actual="x", outcome=outcome)
    report = build_report(store.rules(), log.read())
    assert [(d["date"], d["hit"], d["decided"], d["ratio"]) for d in report["daily"]] == [
        ("2026-10-15", 1, 1, 1.0),
        ("2026-10-16", 1, 2, 0.5),
    ]
    later = build_report(store.rules(), log.read(), since=date(2026, 10, 16))
    assert later["decisions"]["decided"] == 2


def test_replaced_and_retired_rules_leave_the_report(env):
    store, log = env
    record(store, log, "applied", ["R001", "R002"], "p", decision="D1")
    decide(log, "D1", "x", "miss")
    old, new = replace(store, log, "R001", "引けるなら引く")
    retire(store, log, ["R004"])
    report = build_report(store.rules(), log.read())
    assert [r["id"] for r in report["rules"]] == ["R005", "R002", "R003"]
    assert report["conflict_candidates"] == []
    assert log.replacements() == {"R001": "R005"}
    with pytest.raises(RuleError, match=r"R001 \(replaced by R005\)"):
        record(store, log, "applied", ["R001"], "p")


@pytest.mark.parametrize(
    ("reason", "ids"),
    [("conflict", ["R001"]), ("conflict", ["R001", "R001"]), ("no_match", ["R001"]), ("other", [])],
)
def test_escalate_validates_reason_and_ids(env, reason, ids):
    store, log = env
    with pytest.raises(ValueError):
        escalate(store, log, "D1", "p", reason, ids)
    assert log.read() == []


@pytest.mark.parametrize(
    ("decision", "actual", "outcome"),
    [("D 1", "x", "hit"), ("", "x", "hit"), ("D1", " ", "hit"), ("D1", "x", "maybe")],
)
def test_decide_validates(env, decision, actual, outcome):
    _, log = env
    with pytest.raises(ValueError):
        decide(log, decision, actual, outcome)
    assert log.read() == []


def test_read_reports_broken_line(tmp_path):
    (tmp_path / "usage.jsonl").write_text('{"event": "applied"}\n\n{broken\n', encoding="utf-8")
    with pytest.raises(RuleError, match="line 3"):
        UsageLog(tmp_path / "usage.jsonl").read()


def test_decision_is_written_only_when_given(env, tmp_path):
    store, log = env
    record(store, log, "applied", ["R001"], "p")
    record(store, log, "applied", ["R001"], "p", decision="D1")
    lines = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "decision" not in lines[0] and lines[1]["decision"] == "D1"
