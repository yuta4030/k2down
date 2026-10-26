# CLAUDE.md — k2down

k2down = 決断（ke-tsu-dan）= knockdown。決断ルールで問題を次々ダウンさせるライブラリ。

設計の全体像は `DESIGN.md` を参照。このファイルは実装時に必ず守ることをまとめたもの。

## 絶対に守る制約
- **ライブラリ本体は一切通信しない。** HTTP クライアント・ソケット・テレメトリ・更新チェック・自動ダウンロードを入れない
- 依存パッケージも通信しないものに限る。追加する前に必要性を確認し、最小限にする
- LLM / Jev による判定は**インターフェース経由で外から注入**する。コアは誰が判定するかを知らない
- **CLI が本体。** 主な利用者はホスト側の AI エージェントで、人間が直接使うことはあまり想定しない。CLI は判定せず、判定はホスト側に任せる
- CLI とコアは標準ライブラリのみで書く。MCP サーバーは任意（extra: `mcp`）で、判定は **MCP sampling** でホスト側に依頼する

## 技術スタック
- Python 3.11+、パッケージ管理は uv
- CLI は標準ライブラリの argparse。既定の出力は LLM 向けのプレーンテキスト（`ID␣本文`）、`--json` で JSON。エラーは終了コード 1 と stderr（引数の誤りも同じ）
- MCP サーバー（任意）は公式 Python SDK（stdio）
- clone してすぐ動くこと（ビルド工程なし）
- テストは pytest。判定は固定の結果を返すフェイク判定器で行い、テストでも通信しない

## 互換性とリリース
- 利用者との約束は README の「互換性」。CLI の引数、`--json` の出力、`--version` の形、終了コード（0 / 1）、ファイル形式を守る
- `tests/test_contract.py` が約束を確かめる。これが落ちる変更をするなら、マイナー版を上げ、CHANGELOG の「壊れる変更」に書く。キーを足すだけなら壊れる変更ではない（テストにも足す）
- 0.x のうちは、壊れる変更があればマイナー、なければパッチを上げる。`pyproject.toml` と `__version__` をそろえ、`CHANGELOG.md` に `## [<版>] - <日付>` の節を書く
- タグ（`v<版>`）と GitHub Release は、main にマージされたあと CI（`.github/workflows/release.yml`）が作る。手順は `CONTRIBUTING.md`

## 最小版（v0.1）の範囲
- ルールの読み書き（`rules.json`）
- CLI コマンド
  - `k2down list`：全ルールを返す（判定はホスト側が行う）
  - `k2down add RULE`：1 行ルールを追加し、新しい ID を返す（v0.2 までは `--parent ID` があった。v0.3 で範囲に置き換え）
  - `k2down apply --problem P ID...`：適用したルールを記録する
  - `k2down reject --problem P ID...`：人間が却下したルールを記録する
- MCP ツール（任意）
  - `find_rules(problem)`：問題文に当てはまるルールを返す
  - `add_rule(rule)`：1 行ルールを追加し、新しい ID を返す
- 木構造の探索はまだ作らない。全ルールを走査して判定する
- 適用ログを `usage.jsonl` に追記する
- 推論ループ（帰結を追記して再適用）、マージ提案、定期メンテは**v0.1 では作らない**

## v0.2 の範囲
背景は `DESIGN.md` の「v0.2：答え合わせと手入れ」を参照。**k2down は記録と集計だけを行い、意味の判定はホストが行う**原則は変えない。
- 決断 ID：`apply` / `reject` に任意の `--decision ID` を足す。ID はホストが付ける（k2down は採番しない）
- CLI コマンドの追加
  - `k2down decide --decision D [--predicted P] --actual A --outcome hit|miss|none [--problem P]`：予測と人の決断の答え合わせを記録する。`hit` / `miss` はホストが判定して渡す。同じ決断の記録が複数あれば最後のものを使う
  - `k2down escalate --decision D --problem P --reason no_match|conflict [ID...]`：人に聞いたことを記録する（`conflict` のときはぶつかったルール ID を 2 つ以上渡す。`no_match` は ID を取らない）
  - `k2down replace OLD_ID RULE [--source S]`：古いルールと同じ位置に新しい ID のルールを入れて古いルールを消し、新しい ID を返す
  - `k2down retire ID...`：ルールを消す
  - `k2down report [--since DATE]`：ログを集計して手入れの候補を返す（下記）
- `report` が返すもの（数えるだけ。意味の判定はしない）
  - ルールごとの applied / hit / miss / rejected の件数
  - 落とす候補（期間内に一度も当たらない）、書き直す候補（miss・rejected が多い）
  - ぶつかる組の候補（同じ決断で同時に当たり、miss か conflict になった組）
  - 新しいルールの候補（outcome が `none` の決断と人の答え）
  - 日ごとの「ルールで決まった割合」（hit ÷ 記録された決断）
- `add` に任意の `--source TEXT`（ルールの出どころ。1 行）を足す
- MCP の `find_rules` は `{"rules": [...], "escalate": bool}` を返し、当たるルールがなければ `escalate: true` にする
- 置き換え済みの ID を `apply` などに渡したら、エラーに置き換え先を添える（`usage.jsonl` の `replaced` から引く）
- 範囲（scope）は store のディレクトリを分けて扱う（`--dir` / `K2DOWN_DIR`）。タグは作らない（v0.3 で見直し、範囲のタグを入れた）
- ID は使い回さない。消したルールの番号も再発行しないよう、発行済みの最大番号を rules.json に持つ（v0.3 でランダムな ID にし、発行済み番号はやめた）
- v0.2 でも作らないもの：木構造の探索、推論ループ、マージの自動実行、タグ、一致・矛盾・類似の判定

## v0.3 の範囲
背景は `DESIGN.md` の「v0.3：提案と範囲」を参照。algr（k2down を判断ストアとして使うフロー）からの要望が出発点。原則（記録と集計だけ、意味の判定はホスト）は変えない。
- **提案**：ルールになる前の段階を k2down で持つ
  - `k2down propose add RULE` / `propose retire ID` / `propose replace ID RULE`：提案を出し、提案 ID を返す。どれも任意で `--decision` / `--source`、add と replace は `--scope`
  - 中身（種類・対象・文言・範囲）が同じ提案が残っていれば、新しく振らずにその ID を返す。比べるのは文字列の一致だけ（似ているかは判定しない）
  - `k2down proposals`：決まっていない提案を返す
  - `k2down accept PID...`：提案どおりに add / retire / replace する。受け入れられない提案が 1 つでもあれば何も変えない
  - `k2down decline PID... [--reason R]`：却下する。却下も履歴に残る
  - 提案 ID は使い回さない。決まった提案は `proposals.json` から消し、履歴は `usage.jsonl` に残す
- **出どころを分ける**：ルールと提案に `decision`（決断 ID）と `source`（ID で表せない自由記述）を別々に持たせる。既存の `source` に入った決断 ID は k2down では移さない（決断 ID の書式を知らないため。移すならホスト側で）
- **範囲（タグ）**：ルールに `scopes`（範囲の名前の一覧）を持たせる。空なら全体共通
  - `add` / `replace` / `propose` に `--scope`（繰り返し可）。`replace` で省くと古いルールの範囲を引き継ぐ
  - `k2down scope ID... --add S --remove S`：範囲を足し引きする。ID は変えない
  - `k2down list --scope S`：S を持つルールと全体共通のルールを返す。`list --json` は使われている範囲の一覧も返す
  - MCP の `find_rules(problem, scopes?)` / `add_rule(rule, scopes?)`
  - 階層・上書き・範囲の定義ファイルは作らない。ルールの組そのものを分けたいときは store のディレクトリを分ける
- **ルール木をやめる**：rules.json はルールの平らな一覧にする。内部ノード（`N`）と `--parent` はなくす。v1 のファイルは読めるようにし、次の保存で v2 にする
- **report**
  - `add` は `added` イベントを記録する。落とす候補は「足してから `--min-decisions`（既定 10）件以上の決断が記録されたのに一度も当たっていない」ルール。足した記録がなければ期間の初めから数える
  - 提案の数（proposed / accepted / declined / pending）と、却下された提案の一覧を出す
  - 新しいルールの候補に、その決断から出た提案 ID を添える
- **ID をランダムにする**：連番だと、書き間違いが別の実在する ID に当たって黙って記録が狂う。同時に動くエージェントやブランチどうしでも番号がぶつかる
  - ルールは `R-` + 5 文字、提案は `P-` + 5 文字。文字は Crockford base32 の小文字（`0-9` と `i l o u` を除く英小文字）。`secrets` で作る
  - 今あるルール・提案の ID と、`usage.jsonl` に出たことのある ID を避けて振る。発行済み番号（`issued`）は持たない
  - v0.2 までの連番のルール ID（`R001`）はそのまま有効。振り直さない（ログの記録が切れるため）
  - 並び順はファイルの中の順。ID に順番の意味は持たせない
- **ロック**：ファイルを書くコマンドは、store のディレクトリに `.k2down.lock` を `O_CREAT | O_EXCL` で作ってから実行する（標準ライブラリだけ。OS ごとの分岐なし）
  - 取れなければ待って取り直し、10 秒で諦めてエラー。30 秒より古いロックは落ちたプロセスの残りとみなして消す
  - 読むだけのコマンド（`list` / `proposals` / `report`）はロックを取らない。MCP の `find_rules` / `add_rule` も記録の間ロックを取る
- v0.3 でも作らないもの：推論ループ、マージの自動実行、範囲の階層、一致・矛盾・類似の判定

## データ形式

### rules.json（v0.3 から version 2）
```json
{
  "version": 2,
  "rules": [
    { "id": "R-k7m2q", "rule": "外部公開 API の認証は OAuth に統一する", "scopes": ["implement", "plan"] },
    { "id": "R-3xq9a", "rule": "社内バッチ間の認証はサービスアカウントで行う", "note": "notes/R-3xq9a.md", "decision": "I1-4" }
  ]
}
```
- ルールの ID は `R-` + ランダムな 5 文字（v0.2 までの `R` + 3 桁も有効）
- version 1（v0.2 までのルール木。`root` の下に `children` を持つ `N` ノードと `rule` を持つ葉）も読む。葉を木の順に並べた一覧として扱う
- ルールは**自然言語 1 行**。改行を含めない
- `scopes` は任意（v0.3）。範囲の名前（空白なし）の一覧。名前順・重複なしで保存する。空なら全体共通
- `decision` は任意（v0.3）。ルールのもとになった決断 ID
- ID は採番後に変更しない。文言の修正では ID を維持する
- `note` は任意。背景・理由は `notes/<ID>.md` に置く
- `source` は任意（v0.2）。ID で表せない出どころを 1 行で書く（v0.3 から決断 ID は `decision` に入れる）
- `issued`（v0.2 の発行済み最大番号）は v0.3 でやめた。古いファイルにあっても無視する
- 保存時はキー順・インデント（2 スペース）・末尾改行を固定し、git の差分を安定させる
- 統計は rules.json に**入れない**

### proposals.json（v0.3）
決まっていない提案だけを持つ。保存の形式は rules.json と同じく固定する。
```json
{
  "version": 1,
  "proposals": [
    { "id": "P-e7t2r", "kind": "replace", "rule_id": "R-k7m2q", "rule": "...", "decision": "I3-2" }
  ]
}
```
- `kind` は `add`（`rule` を持つ）/ `retire`（`rule_id` を持つ）/ `replace`（両方）
- 任意で `scopes`（add / replace）、`decision`、`source`

### usage.jsonl
1 行 1 イベント。最低限のフィールド：
```json
{"ts": "2026-10-16T09:00:00+09:00", "event": "applied", "rule_id": "R-k7m2q", "problem": "問題文の要約"}
```
- `event` は `applied`（判定で当てはまった）と `rejected`（人間が却下した）を想定
- 追記のみ。既存行は書き換えない
- v0.2 で増えるイベントとフィールド（`decision` はどのイベントでも任意）：
```json
{"ts": "...", "event": "applied", "rule_id": "R-p2w6d", "problem": "...", "decision": "D123"}
{"ts": "...", "event": "decided", "decision": "D123", "predicted": "A", "actual": "B", "outcome": "miss"}
{"ts": "...", "event": "escalated", "decision": "D124", "problem": "...", "reason": "conflict", "rule_ids": ["R-h4n8c", "R-b9t3e"]}
{"ts": "...", "event": "replaced", "rule_id": "R-p2w6d", "replaced_by": "R-z4k6h"}
{"ts": "...", "event": "retired", "rule_id": "R-m5r7f"}
```
- v0.3 で増えるイベント。`added` / `replaced` / `retired` は提案を受け入れて行ったとき `proposal` を持つ：
```json
{"ts": "...", "event": "added", "rule_id": "R-x8c2g", "decision": "D123"}
{"ts": "...", "event": "proposed", "proposal": "P-e7t2r", "kind": "replace", "rule_id": "R-p2w6d", "rule": "...", "decision": "D123"}
{"ts": "...", "event": "accepted", "proposal": "P-e7t2r"}
{"ts": "...", "event": "replaced", "rule_id": "R-p2w6d", "replaced_by": "R-z4k6h", "proposal": "P-e7t2r"}
{"ts": "...", "event": "declined", "proposal": "P-g9w5s", "reason": "..."}
```
- `outcome` は `hit`（予測どおり）/ `miss`（外れ）/ `none`（ルールで予測できず人が決めた）
- `rejected`（ルールが当てはまらなかった）と `miss`（当てはまったが予測が外れた）は別に数える

## ディレクトリ構成（目安）
```
src/k2down/
  cli.py     # CLI（本体。標準ライブラリのみ）
  core/      # ルールと提案の読み書き、判定インターフェース、ログ、集計（通信なし）
  mcp/       # MCP サーバー（任意。sampling で判定）
tests/
```
Jev 等の外部判定アダプタは将来別パッケージにする。このリポジトリのコアには入れない。
