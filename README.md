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
| `k2down list` | 全ルールを返す | 木構造のテキスト（下記） |
| `k2down add RULE [--parent N001] [--source S]` | 1 行ルールを追加する。`--source` は出どころ | `R003` |
| `k2down apply [--decision D] --problem P ID...` | ルールを問題に適用したことを記録する | `applied R001 R003` |
| `k2down reject [--decision D] --problem P ID...` | 適用したルールを人間が却下したことを記録する | `rejected R003` |
| `k2down escalate --decision D --problem P --reason no_match\|conflict [ID...]` | ルールで決まらず人に聞いたことを記録する。`conflict` はぶつかったルールを 2 つ以上渡す | `escalated D12 conflict R003 R017` |
| `k2down decide --decision D [--predicted P] --actual A --outcome hit\|miss\|none [--problem P]` | 予測と人の決断の答え合わせを記録する | `decided D12 miss` |
| `k2down replace ID RULE [--source S]` | ルールを新しい ID のルールに置き換える | `R031` |
| `k2down retire ID...` | ルールを消す | `retired R020` |
| `k2down report [--since YYYY-MM-DD]` | ログを集計し、手入れの候補を返す | 下記 |

`list` の出力は 1 行 1 項目で、「ID␣本文」を木の深さごとに 2 スペースずつ字下げしたものです。

```text
N000 全体
  R001 外部公開 API の認証は OAuth に統一する
  N001 社内認証
    R002 社内バッチ間の認証はサービスアカウントで行う [note: notes/R002.md]
```

- 既定の出力は、LLM が読みやすくトークンの少ないプレーンテキストです（同じ内容の JSON の半分以下）
- `--json` を付けると JSON を返します（`list` は `{"rules": [{"id", "rule", "parent", "note"?}]}`）
- エラー時は終了コード 1 で、stderr に `error: ...`（`--json` なら `{"error": "..."}`）を書きます。存在しない ID を指定したときは何も記録しません
- テキスト引数に `-` を渡すと stdin から読みます

### 答え合わせと手入れ

k2down は記録と集計だけを行い、意味の判定（予測が当たったか、ルール同士が逆を指すか、似ているか）はホスト側が行います。

- **決断 ID**：ホストが決断ごとに空白なしの短い ID（例：`D12`）を付け、`apply` / `reject` / `escalate` / `decide` に渡します。同じ ID の記録がつながり、ルールごとの当たり率が出ます
- **答え合わせ**：`decide --outcome` は `hit`（ルールの予測どおり）/ `miss`（外れ）/ `none`（ルールで予測できず人が決めた）。一致したかどうかはホストが判定します。同じ決断を記録し直したときは最後の記録が使われます
- **人に聞く**：どのルールも当たらない（`no_match`）か、当たったルールがぶつかった（`conflict`）ら `escalate` を記録して人に聞き、答えを `decide --outcome none` で残します
- **置き換えと削除**：`replace` は同じ位置に新しい ID でルールを入れ、古いルールを消して `usage.jsonl` に「旧 ID → 新 ID」を残します。消した ID は二度と発行しません。置き換え済みの ID を指定すると、エラーに置き換え先が出ます
- **範囲**：役や人ごとにルールを分けたいときは、store のディレクトリを分けて `--dir` / `K2DOWN_DIR` で切り替えます

`report` は次の候補を数えて返します（`--since` で期間を絞れます）。

- ルールごとの applied / hit / miss / rejected の件数
- 落とす候補（一度も当たっていない）、書き直す候補（miss と rejected が多い順）
- ぶつかる組の候補（同じ決断で同時に当たって外れた組と、`conflict` で人に聞いた組）
- 新しいルールの候補（`none` の決断と人の答え）
- 日ごとの「ルールで決まった割合」（hit ÷ 記録された決断）

### AI エージェントに使わせる

`k2down --help` にエージェント向けの手順を書いてあります。プロジェクトの `CLAUDE.md` などに次のように書いておけば十分です。

```markdown
## 決断ルール
設計判断の前に `k2down list` で決断ルールを確認し、当てはまるものに従う。
決断ごとに短い ID（例：D12）を付け、従ったルールは `k2down apply --decision D12 --problem "<問題の要約>" <ID...>` で記録する。
どのルールも当たらないか、ルール同士がぶつかったら `k2down escalate` を記録して人間に聞く。
人間が決めたら `k2down decide` で予測が当たったか（hit / miss / none）を記録する。
ルールが無い新しい汎用的な判断をしたら、人間に確認してから `k2down add "<1 行ルール>" --source D12` で追加する。
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
| `find_rules(problem)` | 問題文に当てはまるルールを `{"rules": [...], "escalate": bool}` で返し、`usage.jsonl` に `applied` として記録する。当てはまるルールがなければ `escalate` が `true`（人に聞く） |
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
- ID は一度採番したら変えず、消した ID も再発行しない。`issued` に発行済みの最大番号を持つ
- `note` は任意。背景・理由は `notes/<ID>.md` に置く
- `source` は任意。ルールの出どころ（どの決断・どのセッションから生まれたか）
- 統計は入れない

### usage.jsonl

1 行 1 イベントの追記専用ログです。`decision` はどのイベントでも任意です。

```json
{"ts": "2026-10-16T09:00:00+09:00", "event": "applied", "rule_id": "R001", "problem": "問題文の要約", "decision": "D12"}
{"ts": "...", "event": "rejected", "rule_id": "R001", "problem": "..."}
{"ts": "...", "event": "decided", "decision": "D12", "predicted": "A", "actual": "B", "outcome": "miss"}
{"ts": "...", "event": "escalated", "decision": "D13", "problem": "...", "reason": "conflict", "rule_ids": ["R003", "R017"]}
{"ts": "...", "event": "replaced", "rule_id": "R012", "replaced_by": "R031"}
{"ts": "...", "event": "retired", "rule_id": "R020"}
```

## 開発

```sh
uv run pytest
```

テストは固定の結果を返すフェイク判定器で行い、通信しません。
`src/k2down` が通信用モジュールを import していないことと、CLI とコアが標準ライブラリだけで書かれていることもテストで確認しています。

## ライセンス

[MIT](LICENSE)
