# k2down

k2down = 決断（ke-tsu-dan）= knockdown。
自然言語で書いた決断ルールを新しい問題に当てはめ、決まる部分を次々ダウンさせるライブラリです。

設計の全体像は [DESIGN.md](DESIGN.md) を参照してください。

## 特徴

- **CLI が本体。** 主な利用者はホスト側の AI エージェント（Claude Code 等）で、人間が直接打つことはあまり想定していない
- **k2down 自身は判定しない。** ルールを渡すだけで、当てはまるかどうかはホスト側の AI が決め、その結果を記録させる
- **一切通信しない。** CLI とコアは Python 標準ライブラリだけで動き、依存パッケージはゼロ
- ルールは自然言語 1 行。`rules.json` に平らな一覧で保存し、git で差分を追いやすい形式で書き出す。範囲はタグ（`scopes`）で付ける
- 適用ログはローカルの `usage.jsonl` に追記するだけ。テレメトリはない

## 必要なもの

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## CLI

```sh
uv tool install git+https://github.com/yuta4030/k2down@v0.4.0   # k2down コマンドを PATH に入れる（clone 不要・依存ゼロ）
k2down --dir /path/to/your/rules list
```

`@v0.4.0` のようにタグを付けると版を固定できます（版の一覧は [CHANGELOG](CHANGELOG.md)）。付けなければ main の最新が入ります。

入れずに試すだけなら `uvx --from git+https://github.com/yuta4030/k2down k2down list` でも動きます。
手元で clone した場合は `uv tool install ./k2down`、または `uv run --directory /path/to/k2down k2down ...` を使います。

`--dir`（省略時は環境変数 `K2DOWN_DIR`、それもなければカレントディレクトリ）にある `rules.json`・`proposals.json`・`usage.jsonl` を読み書きします。ファイルがなければ最初の `add` で作られます。

| コマンド | 説明 | 出力 |
|---|---|---|
| `k2down list [--scope S]...` | ルールを返す。`--scope` を付けるとその範囲と全体共通のルールだけ | 1 行 1 ルール（下記） |
| `k2down scope ID... [--add S]... [--remove S]...` | ルールの範囲を足し引きする（ID は変わらない） | 変えたルール |
| `k2down add RULE [--scope S]... [--decision D] [--source S]` | 1 行ルールを追加する | `R-h4n8c` |
| `k2down apply [--decision D] --problem P ID...` | ルールを問題に適用したことを記録する | `applied R-k7m2q R-h4n8c` |
| `k2down reject [--decision D] --problem P ID...` | 適用したルールを人間が却下したことを記録する | `rejected R-h4n8c` |
| `k2down escalate --decision D --problem P --reason no_match\|conflict [ID...]` | ルールで決まらず人に聞いたことを記録する。`conflict` はぶつかったルールを 2 つ以上渡す | `escalated D12 conflict R-h4n8c R-b9t3e` |
| `k2down decide --decision D [--predicted P] --actual A --outcome hit\|miss\|none [--problem P]` | 予測と人の決断の答え合わせを記録する | `decided D12 miss` |
| `k2down replace ID RULE [--scope S]... [--decision D] [--source S]` | ルールを新しい ID のルールに置き換える。`--scope` を省くと範囲を引き継ぐ | `R-z4k6h` |
| `k2down retire ID...` | ルールを消す | `retired R-m5r7f` |
| `k2down propose add RULE [--scope S]... [--decision D] [--source S] [--reason R]` | ルールを足す提案を出す | `P-a2m4n` |
| `k2down propose retire ID [--decision D] [--source S] [--reason R]` | ルールを外す提案を出す | `P-c5q8p` |
| `k2down propose replace ID RULE [--scope S]... [--decision D] [--source S] [--reason R]` | ルールを置き換える提案を出す | `P-e7t2r` |
| `k2down proposals` | 決まっていない提案を返す | `P-a2m4n add <本文> [decision: I3-2]` |
| `k2down accept PID...` | 提案を受け入れ、ルールに反映する | `accepted P-a2m4n add R-v7d3j` |
| `k2down decline PID... [--reason R]` | 提案を却下する（履歴に残る） | `declined P-c5q8p` |
| `k2down report [--since YYYY-MM-DD] [--min-decisions N]` | ログを集計し、手入れの候補を返す | 下記 |

`list` の出力は 1 行 1 ルールの「ID␣本文」で、範囲・決断 ID・出どころ・note があれば後ろに付きます。

```text
R-k7m2q 外部公開 API の認証は OAuth に統一する [scopes: implement plan]
R-3xq9a 社内バッチ間の認証はサービスアカウントで行う [decision: I1-4] [note: notes/R-3xq9a.md]
R-h4n8c 実装の細部はエージェントが決める
```

- 既定の出力は、LLM が読みやすくトークンの少ないプレーンテキストです（同じ内容の JSON の半分以下）
- `--json` を付けると JSON を返します（`list` は `{"rules": [{"id", "rule", "scopes"?, "decision"?, "source"?, "note"?}], "scopes": [使われている範囲]}`）
- エラー時は終了コード 1 で、stderr に `error: ...`（`--json` なら `{"error": "..."}`）を書きます。引数の誤りも同じです。存在しない ID を指定したときは何も記録しません
- テキスト引数に `-` を渡すと stdin から読みます
- ID は連番ではなくランダムです。書き間違えた ID はほぼ確実に「ない ID」としてエラーになり、別のルールに記録されることはありません。同時に動くエージェントやブランチどうしでも ID がぶつかりません

### 同時に使う

ファイルを書き換えるコマンドは、store のディレクトリに `.k2down.lock` を作ってから実行し、終わったら消します。複数のエージェントが同時に k2down を呼んでも、書き込みが混ざったり消えたりしません。

- ロックが取れなければ少し待って取り直し、10 秒たっても取れなければエラーになります
- プロセスが落ちて残ったロックは、30 秒たてば古いものとみなして取り除きます
- 読むだけのコマンド（`list` / `proposals` / `report`）はロックを待ちません
- store を git で管理しているなら、`.k2down.lock` を `.gitignore` に入れてください

### 答え合わせと手入れ

k2down は記録と集計だけを行い、意味の判定（予測が当たったか、ルール同士が逆を指すか、似ているか）はホスト側が行います。

- **決断 ID**：ホストが決断ごとに空白なしの短い ID（例：`D12`）を付け、`apply` / `reject` / `escalate` / `decide` に渡します。同じ ID の記録がつながり、ルールごとの当たり率が出ます
- **答え合わせ**：`decide --outcome` は `hit`（ルールの予測どおり）/ `miss`（外れ）/ `none`（ルールで予測できず人が決めた）。一致したかどうかはホストが判定します。同じ決断を記録し直したときは最後の記録が使われます
- **人に聞く**：どのルールも当たらない（`no_match`）か、当たったルールがぶつかった（`conflict`）ら `escalate` を記録して人に聞き、答えを `decide --outcome none` で残します
- **置き換えと削除**：`replace` は同じ位置に新しい ID でルールを入れ、古いルールを消して `usage.jsonl` に「旧 ID → 新 ID」を残します。消した ID は二度と発行しません。置き換え済みの ID を指定すると、エラーに置き換え先が出ます
- **範囲**：ルールに範囲の名前（例：`plan`、`implement`、`review`）をいくつでも付けられます。範囲のないルールは全体共通です。`list --scope implement` は `implement` を持つルールと全体共通のルールを返します。階層や上書きはありません。ルールの組そのものを分けたいとき（役や人ごと、木のように分けたいとき）は、store のディレクトリを分けて `--dir` / `K2DOWN_DIR` で切り替えます
- **出どころ**：`--decision` はルールのもとになった決断 ID、`--source` は ID で表せない出どころの自由記述です。別の項目に入ります

### 提案

ルールを変えるとき、エージェントは直接 `add` / `replace` / `retire` するかわりに提案を出し、人が受け入れたものだけをルールにできます。

- 提案は足す（`add`）・外す（`retire`）・置き換える（`replace`）の 3 種類。ID は `P-` + ランダムな 5 文字で、使い回しません
- `--reason` はなぜ変えるか（1 行）。出どころ（`--decision` / `--source`）とは別の項目です
- 中身（種類・対象のルール・文言・範囲）が同じ提案が残っていれば、新しく振らずにその ID を返します。再送しても増えません。同じかどうかは文字列の一致で見ます（似ているかの判定はしません）
- `accept` は提案どおりに `add` / `retire` / `replace` を行います。受け入れられない提案（対象のルールがもうない、同じルールを対象にした提案を一度に受け入れる）が 1 つでもあれば、何も変えずにエラーになります
- 決まった提案は `proposals.json` から消え、出した・受け入れた・却下した記録が `usage.jsonl` に残ります。決まった提案の ID を渡すと、エラーにどう決まったかが出ます

`report` は次の候補を数えて返します（`--since` で期間を絞れます）。

- ルールごとの applied / hit / miss / rejected の件数
- 落とす候補（足してから `--min-decisions`（既定 10）件以上の決断が記録されたのに、一度も当たっていない）。足したばかりのルールは入りません。足した記録のない v0.2 以前のルールは、期間の初めから数えます
- 書き直す候補（miss と rejected が多い順）
- ぶつかる組の候補（同じ決断で同時に当たって外れた組と、`conflict` で人に聞いた組）
- 新しいルールの候補（`none` の決断と人の答え、その決断から出た提案の ID）
- 提案の数（出した・受け入れた・却下した・残っている）と、却下された提案の一覧（`reason` は提案の理由、`decline_reason` は却下の理由）
- 日ごとの「ルールで決まった割合」（hit ÷ 記録された決断）

### AI エージェントに使わせる

`k2down --help` にエージェント向けの手順を書いてあります。プロジェクトの `CLAUDE.md` などに次のように書いておけば十分です。

```markdown
## 決断ルール
設計判断の前に `k2down list` で決断ルールを確認し、当てはまるものに従う。
決断ごとに短い ID（例：D12）を付け、従ったルールは `k2down apply --decision D12 --problem "<問題の要約>" <ID...>` で記録する。
どのルールも当たらないか、ルール同士がぶつかったら `k2down escalate` を記録して人間に聞く。
人間が決めたら `k2down decide` で予測が当たったか（hit / miss / none）を記録する。
ルールが無い新しい汎用的な判断をしたら、`k2down propose add "<1 行ルール>" --decision D12` で提案し、人間が受け入れたら `k2down accept <P...>` する。
使い方の詳細は `k2down --help`。
```

## MCP サーバー（任意）

CLI を使えない環境向けに、MCP サーバー（stdio）も用意しています。判定は MCP sampling でホスト側に依頼します。
公式 MCP SDK に依存するため、`--extra mcp` を付けたときだけ入ります。

```sh
uvx --from 'k2down[mcp] @ git+https://github.com/yuta4030/k2down' k2down-mcp --dir /path/to/your/rules
```

Claude Code に登録する例：

```sh
claude mcp add k2down -- uvx --from 'k2down[mcp] @ git+https://github.com/yuta4030/k2down' k2down-mcp --dir /path/to/your/rules
```

手元で clone した場合は `uv run --directory /path/to/k2down --extra mcp k2down-mcp --dir ...` でも動きます。

| ツール | 説明 |
|---|---|
| `find_rules(problem, scopes?)` | 問題文に当てはまるルールを `{"rules": [...], "escalate": bool}` で返し、`usage.jsonl` に `applied` として記録する。`scopes` を渡すとその範囲と全体共通のルールだけを見る。当てはまるルールがなければ `escalate` が `true`（人に聞く） |
| `add_rule(rule, scopes?)` | 1 行ルールを追加し、新しい ID を返す |

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
  "rules": [
    {
      "id": "R-k7m2q",
      "rule": "外部公開 API の認証は OAuth に統一する",
      "scopes": ["implement", "plan"]
    },
    {
      "decision": "I1-4",
      "id": "R-3xq9a",
      "rule": "社内バッチ間の認証はサービスアカウントで行う"
    }
  ],
  "version": 2
}
```

- ルールの ID は `R-` + ランダムな 5 文字（数字と、見間違えやすい i l o u を除く英小文字）。一度採番したら変えず、消した ID も再発行しない（`usage.jsonl` に出たことのある ID を避けて振る）。v0.2 までの連番の ID（`R001`）もそのまま有効
- `scopes` は任意。範囲の名前（空白なし）の一覧で、なければ全体共通
- `decision` は任意。ルールのもとになった決断 ID
- `source` は任意。ID で表せない出どころの自由記述（1 行）
- `note` は任意。背景・理由は `notes/<ID>.md` に置く
- 統計は入れない
- v0.2 までの木構造のファイル（`"version": 1`）もそのまま読めます。ルールを木の順に並べた一覧として扱い、次に書き込んだときに `"version": 2` になります（グループのノードは消えます）

### proposals.json

決まっていない提案だけを持ちます。

```json
{
  "proposals": [
    {"decision": "I3-2", "id": "P-e7t2r", "kind": "replace", "rule": "引けるなら引く", "rule_id": "R-k7m2q"}
  ],
  "version": 1
}
```

### usage.jsonl

1 行 1 イベントの追記専用ログです。`decision` はどのイベントでも任意です。

```json
{"ts": "2026-10-16T09:00:00+09:00", "event": "applied", "rule_id": "R-k7m2q", "problem": "問題文の要約", "decision": "D12"}
{"ts": "...", "event": "rejected", "rule_id": "R-k7m2q", "problem": "..."}
{"ts": "...", "event": "decided", "decision": "D12", "predicted": "A", "actual": "B", "outcome": "miss"}
{"ts": "...", "event": "escalated", "decision": "D13", "problem": "...", "reason": "conflict", "rule_ids": ["R-h4n8c", "R-b9t3e"]}
{"ts": "...", "event": "added", "rule_id": "R-x8c2g", "decision": "D12"}
{"ts": "...", "event": "replaced", "rule_id": "R-p2w6d", "replaced_by": "R-z4k6h", "proposal": "P-e7t2r"}
{"ts": "...", "event": "retired", "rule_id": "R-m5r7f"}
{"ts": "...", "event": "proposed", "proposal": "P-e7t2r", "kind": "replace", "rule_id": "R-p2w6d", "rule": "...", "decision": "D12", "reason": "..."}
{"ts": "...", "event": "accepted", "proposal": "P-e7t2r"}
{"ts": "...", "event": "declined", "proposal": "P-g9w5s", "reason": "..."}
```

`added` / `replaced` / `retired` は、提案を受け入れて行ったときに `proposal` を持ちます。

## 互換性

k2down を道具から呼ぶ利用者（AI エージェントのフローなど）のために、次のものを約束として扱います。

- **守るもの**
  - CLI のコマンド名・引数
  - `--json` の出力の形（キーの名前と意味）
  - `k2down --version` の出力（`k2down X.Y.Z`。最後の語が版）
  - 終了コード（成功は 0、エラーは 1）と、`--json` のときのエラーの形（stderr に `{"error": "..."}`）
  - ファイルの形式（`rules.json` / `proposals.json` / `usage.jsonl`）
- **壊れる変更とみなさないもの**
  - `--json` の出力やファイルに、キーやイベントを足すこと。利用側は知らないキーやイベントを無視してください
  - 既定のテキスト出力の細かな形。テキストは LLM が読むためのもので、機械で読むなら `--json` を使ってください（大きく変えるときは CHANGELOG に書きます）
  - エラーメッセージの文言
- **版の付け方**：[セマンティック バージョニング](https://semver.org/lang/ja/)に従います。1.0 より前は、壊れる変更があればマイナー（0.4 → 0.5）、なければパッチ（0.4.0 → 0.4.1）を上げます。変わったことは [CHANGELOG](CHANGELOG.md) に書き、壊れる変更は別の見出しにします
- **タグ**：0.4.0 以降の各版に `v<版>` のタグと GitHub Release があります
- **ファイルの版**：`rules.json` と `proposals.json` は `version` を持ちます。古い版のファイルは読めるように保ち、新しい k2down が書いたファイルを古い k2down で読むと、更新を促すエラーになります

## 開発

```sh
uv run pytest
```

テストは固定の結果を返すフェイク判定器で行い、通信しません。
`src/k2down` が通信用モジュールを import していないことと、CLI とコアが標準ライブラリだけで書かれていることもテストで確認しています。
互換性の約束は `tests/test_contract.py` で確かめています。リリースの手順は [CONTRIBUTING](CONTRIBUTING.md) にあります。

## ライセンス

[MIT](LICENSE)
