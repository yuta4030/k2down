"""MCP サーバーをプロセス内クライアントで叩く。sampling はフェイクの応答を返す。"""

import asyncio
import json

import pytest
from mcp import Client, types

from k2down.mcp.judge import parse_ids
from k2down.mcp.server import create_server


def make_sampler(reply, seen):
    async def sampling_callback(context, params):
        seen.append(params)
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=reply),
            model="fake",
        )

    return sampling_callback


def call(server, name, arguments, reply="[]", seen=None):
    async def run():
        async with Client(server, sampling_callback=make_sampler(reply, seen if seen is not None else [])) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content


def test_add_then_find(tmp_path):
    server = create_server(tmp_path)
    assert payload(call(server, "add_rule", {"rule": "外部公開 API の認証は OAuth に統一する"})) == {"id": "R001"}
    assert payload(call(server, "add_rule", {"rule": "ログは JSON で出す"})) == {"id": "R002"}

    seen = []
    result = call(server, "find_rules", {"problem": "公開 API を新設する"}, reply='答え: ["R001"]', seen=seen)
    assert result.structured_content == {
        "rules": [{"id": "R001", "rule": "外部公開 API の認証は OAuth に統一する"}],
        "escalate": False,
    }

    prompt = seen[0].messages[0].content.text
    assert "公開 API を新設する" in prompt and "R001: 外部公開" in prompt and "R002: ログは" in prompt

    usage = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(u["event"], u["rule_id"]) for u in usage] == [("applied", "R001")]


def test_find_without_rules_does_not_sample(tmp_path):
    seen = []
    result = call(create_server(tmp_path), "find_rules", {"problem": "何か"}, reply='["R001"]', seen=seen)
    assert result.structured_content == {"rules": [], "escalate": True}
    assert seen == []
    assert not (tmp_path / "usage.jsonl").exists()


def test_find_no_match_escalates(tmp_path):
    server = create_server(tmp_path)
    call(server, "add_rule", {"rule": "ログは JSON で出す"})
    result = call(server, "find_rules", {"problem": "公開 API を新設する"}, reply="[]")
    assert result.structured_content == {"rules": [], "escalate": True}


def test_find_rules_schema_exposes_only_problem(tmp_path):
    async def run():
        async with Client(create_server(tmp_path)) as client:
            return {tool.name: tool.input_schema for tool in (await client.list_tools()).tools}

    schemas = asyncio.run(run())
    assert set(schemas["find_rules"]["properties"]) == {"problem"}
    assert set(schemas["add_rule"]["properties"]) == {"rule", "parent_id"}


def test_add_rule_rejects_multiline(tmp_path):
    result = call(create_server(tmp_path), "add_rule", {"rule": "a\nb"})
    assert result.is_error
    assert not (tmp_path / "rules.json").exists()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('["R001", "R003"]', ["R001", "R003"]),
        ("```json\n[\"R002\"]\n```", ["R002"]),
        ("[]", []),
        ("R004 と R010 が該当", ["R004", "R010"]),
        ('["R001", 3, "x"]', ["R001"]),
    ],
)
def test_parse_ids(text, expected):
    assert parse_ids(text) == expected
