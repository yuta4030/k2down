# k2down

k2down = 決断（ke-tsu-dan）= knockdown。
自然言語で書いた決断ルールを新しい問題に当てはめ、決まる部分を次々ダウンさせるライブラリです。

設計の全体像は [DESIGN.md](DESIGN.md) を参照してください。

## 特徴

- **CLI が本体。** 主な利用者はホスト側の AI エージェント（Claude Code 等）で、人間が直接打つことはあまり想定していない
- **k2down 自身は判定しない。** ルールを渡すだけで、当てはまるかどうかはホスト側の AI が決め、その結果を記録させる
- **一切通信しない。** CLI とコアは Python 標準ライブラリだけで動き、依存パッケージはゼロ
- ルールは自然言語 1 行。`rules.json` に木構造で保存し、git で差分を追いやすい形式で書き出す
- 適用ログはローカルの `usage.jsonl` に追記するだけ。テレメトリはない

## 必要なもの

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## CLI

```sh
git clone https://github.com/yuta4030/k2down.git
uv tool install ./k2down   # k2down コマンドを PATH に入れる（依存ゼロなので追加のダウンロードなし）
k2down --dir /path/to/your/rules list
```

インストールせずに `uv run --directory /path/to/k2down k2down ...` や `python -m k2down ...`（`src` を `PYTHONPATH` に入れた場合）でも動きます。

`--dir`（省略時は環境変数 `K2DOWN_DIR`、それもなければカレントディレクトリ）にある `rules.json` と `usage.jsonl` を読み書きします。ファイルがなければ最初の `add` で作られます。

| コマンド | 説明 | 出力 |
|---|---|---|
| `k2down list` | 全ルールを返す | `{"rules": [{"id", "rule", "parent", "note"?}]}` |
| `k2down add RULE [--parent N001]` | 1 行ルールを追加する | `{"id": "R003"}` |
| `k2down apply --problem P ID...` | ルールを問題に適用したことを記録する | `{"applied": [...]}` |
| `k2down reject --problem P ID...` | 適用したルールを人間が却下したことを記録する | `{"rejected": [...]}` |

- 出力は常に JSON 1 個を stdout に書きます
- エラー時は終了コード 1 で、`{"error": "..."}` を stderr に書きます。存在しない ID を指定したときは何も記録しません
- テキスト引数に `-` を渡すと stdin から読みます

### AI エージェントに使わせる

`k2down --help` にエージェント向けの手順を書いてあります。プロジェクトの `CLAUDE.md` などに次のように書いておけば十分です。

```markdown
## 決断ルール
設計判断の前に `k2down list` で決断ルールを確認し、当てはまるものに従う。
従ったルールは `k2down apply --problem "<問題の要約>" <ID...>` で記録する。
ルールが無い新しい汎用的な判断をしたら、人間に確認してから `k2down add "<1 行ルール>"` で追加する。
使い方の詳細は `k2down --help`。
```

## MCP サーバー（任意）

CLI を使えない環境向けに、MCP サーバー（stdio）も用意しています。判定は MCP sampling でホスト側に依頼します。
公式 MCP SDK に依存するため、`--extra mcp` を付けたときだけ入ります。

```sh
uv run --directory /path/to/k2down --extra mcp k2down-mcp --dir /path/to/your/rules
```

| ツール | 説明 |
|---|---|
| `find_rules(problem)` | 問題文に当てはまるルールを返し、`usage.jsonl` に `applied` として記録する |
| `add_rule(rule, parent_id?)` | 1 行ルールを追加し、新しい ID を返す |

## ライブラリとして使う

```python
from k2down.core import RuleStore, UsageLog, record

store = RuleStore("rules.json")
rule = store.add_rule("外部公開 API の認証は OAuth に統一する")
record(store, UsageLog("usage.jsonl"), "applied", [rule.id], "公開 API を新設する")
```

判定器（`select(problem, rules) -> list[str]` を持つ非同期オブジェクト）を自分で用意すれば、`find_rules` で判定から記録までまとめて行えます。

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
`src/k2down` が通信用モジュールを import していないことと、CLI とコアが標準ライブラリだけで書かれていることもテストで確認しています。

## ライセンス

[MIT](LICENSE)
