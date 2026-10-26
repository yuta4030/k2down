# CHANGELOG

k2down の版ごとの変更です。版の付け方と、何を「壊れる変更」とみなすかは [README の「互換性」](README.md#互換性) を参照してください。
各版には `v<版>` のタグがあり、`uv tool install git+https://github.com/yuta4030/k2down@v0.4.0` のように固定して入れられます。

## [0.4.0] - 2026-10-26

### 壊れる変更
- `replace --json` の出力を `{"id", "replaced"}` から `{"rule_id", "replaced_by"}` に変えた。`accept` で置き換えたときや `usage.jsonl` の `replaced` と同じ名前にそろえた
- 引数の誤り（知らないコマンド、必須の引数がないなど）も、ほかのエラーと同じく終了コード 1 にした（これまでは argparse の既定の 2）。`--json` なら `{"error": "..."}` を stderr に書く

### 追加
- README に「互換性」の節を追加。守る範囲（CLI の引数、`--json` の出力、`--version`、終了コード、ファイル形式）と版の付け方を明記した
- 利用者との約束を確かめるテスト（`tests/test_contract.py`）
- リリースの自動化。main の版にタグがなければ、CI が `v<版>` のタグと GitHub Release を作る（`.github/workflows/release.yml`、手順は `CONTRIBUTING.md`）

### 変更
- 新しい k2down が書いた `rules.json` / `proposals.json` を読んだとき、k2down の更新を促すエラーにした

## [0.3.0] - 2026-10-26

### 壊れる変更
- ルール木をやめ、`rules.json` を平らな一覧（version 2）にした。version 1 のファイルも読め、次に書き込んだときに変換される（グループのノードは消える）
- `add --parent`、MCP の `add_rule(parent_id)`、`list --json` の `parent` を削除
- 新しく振る ID をランダムにした（ルール `R-k7m2q`、提案 `P-3xq9a`）。v0.2 までの `R001` 形式はそのまま有効。`rules.json` の `issued` は使わない
- `add` が `usage.jsonl` に `added` を記録するようになった

### 追加
- 提案：`propose add|retire|replace`、`proposals`、`accept`、`decline --reason`。決まっていない提案は `proposals.json`、履歴は `usage.jsonl`
- 範囲のタグ：ルールの `scopes`、`list --scope`、`scope ID... --add/--remove`、MCP の `find_rules(problem, scopes?)` / `add_rule(rule, scopes?)`
- ルールと提案の `decision`（決断 ID）。`source` は ID で表せない自由記述に限る
- `report`：`--min-decisions`、ルールごとの `decisions`（足してからの判断の数）、`proposals`、`declined_proposals`、新しいルールの候補の `proposals`
- 書き込むコマンドのロック（store のディレクトリの `.k2down.lock`）

### 変更
- `report` の落とす候補は、足してから `--min-decisions`（既定 10）件以上の判断があって一度も当たっていないルールに限った

## [0.2.0] - 2026-10-19

### 追加
- 決断 ID（`--decision`）で `apply` / `reject` / `decide` / `escalate` の記録をつなぐ
- `decide`：予測と人の決断の答え合わせ（`hit` / `miss` / `none`）
- `escalate`：ルールで決まらず人に聞いたこと（`no_match` / `conflict`）
- `replace` / `retire`、`add --source`
- `report`：ルールごとの件数と、手入れの候補
- MCP の `find_rules` が `escalate` を返す

## [0.1.0] - 2026-10-17

### 追加
- 最初の版。`rules.json`（ルール木）と `usage.jsonl`、CLI の `list` / `add` / `apply` / `reject`、MCP サーバー（任意）の `find_rules` / `add_rule`
- 既定の出力は LLM 向けのプレーンテキスト、`--json` で JSON
