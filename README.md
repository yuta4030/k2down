# k2down

k2down = 決断（ke-tsu-dan）= knockdown。
自然言語で書いた決断ルールを新しい問題に当てはめ、決まる部分を次々ダウンさせるライブラリです。

設計の全体像は [DESIGN.md](DESIGN.md) を参照してください。

## 特徴

- ルールは自然言語 1 行。`rules.json` に木構造で保存し、git で差分を追いやすい形式で書き出す
- **ライブラリ本体は一切通信しない。** 判定は外から注入し、MCP サーバーでは MCP sampling でホスト側（Claude Code 等）の LLM に依頼する
- コアは依存パッケージゼロ（Python 標準ライブラリのみ）
- 適用ログはローカルの `usage.jsonl` に追記するだけ。テレメトリはない

## 必要なもの

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## MCP サーバーとして使う（v0.1）

```sh
git clone https://github.com/yuta4030/k2down.git
cd k2down
uv run --extra mcp k2down-mcp --dir /path/to/your/rules
```

`--dir`（省略時は環境変数 `K2DOWN_DIR`、それもなければカレントディレクトリ）にある `rules.json` と `usage.jsonl` を読み書きします。ファイルがなければ最初の `add_rule` で作られます。

Claude Code に登録する例:

```sh
claude mcp add k2down -- uv run --directory /path/to/k2down --extra mcp k2down-mcp --dir /path/to/your/rules
```

ホスト側が MCP sampling に対応している必要があります。

### ツール

| ツール | 説明 |
|---|---|
| `find_rules(problem)` | 問題文に当てはまるルールを返す。当てはまったものは `usage.jsonl` に `applied` として記録する |
| `add_rule(rule, parent_id?)` | 1 行ルールを追加し、新しい ID（`R001` など）を返す |

## ライブラリとして使う

判定器は `select(problem, rules) -> list[str]`（非同期）を持つオブジェクトなら何でも構いません。

```python
import asyncio
from k2down.core import RuleStore, UsageLog, find_rules

class MyJudge:
    async def select(self, problem, rules):
        return [r.id for r in rules if "API" in problem and "API" in r.rule]

store = RuleStore("rules.json")
store.add_rule("外部公開 API の認証は OAuth に統一する")
print(asyncio.run(find_rules(store, MyJudge(), "公開 API を新設する", UsageLog("usage.jsonl"))))
```

## データ形式

### rules.json

```json
{
  "root": {
    "children": [
      {
        "id": "R001",
        "rule": "外部公開 API の認証は OAuth に統一する"
      }
    ],
    "id": "N000",
    "summary": "全体"
  },
  "version": 1
}
```

- `children` を持つものが内部ノード（`N` + 3 桁）、`rule` を持つものが葉（`R` + 3 桁）
- ID は一度採番したら変えない
- `note` は任意。背景・理由は `notes/<ID>.md` に置く
- 統計は入れない

### usage.jsonl

```json
{"ts": "2026-10-16T09:00:00+09:00", "event": "applied", "rule_id": "R001", "problem": "問題文の要約"}
```

## 開発

```sh
uv run pytest
```

テストは固定の結果を返すフェイク判定器で行い、通信しません。
`src/k2down` が通信用モジュールを import していないことと、コアが標準ライブラリだけで書かれていることもテストで確認しています。

## ライセンス

[MIT](LICENSE)
