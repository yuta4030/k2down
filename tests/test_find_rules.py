import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeJudge
from k2down.core import RuleStore, UsageLog, find_rules


@pytest.fixture
def store(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    store.add_rule("外部公開 API の認証は OAuth に統一する")
    store.add_rule("社内バッチ間の認証はサービスアカウントで行う")
    store.add_rule("ログは JSON で出す")
    return store


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_returns_matched_rules_in_tree_order_and_logs(store, tmp_path):
    log = UsageLog(tmp_path / "usage.jsonl")
    judge = FakeJudge(["R-00003", "R-00001"])
    matched = asyncio.run(find_rules(store, judge, "新しい公開 API を作る", log))
    assert [r.id for r in matched] == ["R-00001", "R-00003"]
    assert judge.calls == [("新しい公開 API を作る", ["R-00001", "R-00002", "R-00003"])]
    events = read_log(tmp_path / "usage.jsonl")
    assert [(e["event"], e["rule_id"], e["problem"]) for e in events] == [
        ("applied", "R-00001", "新しい公開 API を作る"),
        ("applied", "R-00003", "新しい公開 API を作る"),
    ]
    datetime.fromisoformat(events[0]["ts"])


def test_ignores_unknown_and_duplicate_ids(store, tmp_path):
    log = UsageLog(tmp_path / "usage.jsonl")
    matched = asyncio.run(find_rules(store, FakeJudge(["R-00002", "R-00999", "R-00002"]), "p", log))
    assert [r.id for r in matched] == ["R-00002"]
    assert len(read_log(tmp_path / "usage.jsonl")) == 1


def test_no_match_writes_nothing(store, tmp_path):
    log = UsageLog(tmp_path / "usage.jsonl")
    assert asyncio.run(find_rules(store, FakeJudge([]), "p", log)) == []
    assert not (tmp_path / "usage.jsonl").exists()


def test_empty_store_skips_judge(tmp_path):
    judge = FakeJudge(["R-00001"])
    assert asyncio.run(find_rules(RuleStore(tmp_path / "rules.json"), judge, "p")) == []
    assert judge.calls == []


def test_rejects_empty_problem(store):
    with pytest.raises(ValueError):
        asyncio.run(find_rules(store, FakeJudge([]), "  "))


def test_usage_log_appends_only(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text('{"existing": true}\n', encoding="utf-8")
    log = UsageLog(path)
    ts = datetime(2026, 10, 16, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    log.append("rejected", "R-00001", "長い\n問題文", ts=ts)
    assert read_log(path) == [
        {"existing": True},
        {"ts": "2026-10-16T09:00:00+09:00", "event": "rejected", "rule_id": "R-00001", "problem": "長い 問題文"},
    ]
    with pytest.raises(ValueError):
        log.append("unknown", "R-00001", "p")


def test_usage_log_truncates_long_problem(tmp_path):
    log = UsageLog(tmp_path / "usage.jsonl")
    log.append("applied", "R-00001", "あ" * 500)
    assert len(read_log(tmp_path / "usage.jsonl")[0]["problem"]) == 200
