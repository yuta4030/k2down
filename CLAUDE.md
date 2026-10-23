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
- CLI は標準ライブラリの argparse。既定の出力は LLM 向けのプレーンテキスト（`ID␣本文`、木はインデント）、`--json` で JSON。エラーは終了コード 1 と stderr
- MCP サーバー（任意）は公式 Python SDK（stdio）
- clone してすぐ動くこと（ビルド工程なし）
- テストは pytest。判定は固定の結果を返すフェイク判定器で行い、テストでも通信しない

## 最小版（v0.1）の範囲
- ルールの読み書き（`rules.json`）
- CLI コマンド
  - `k2down list`：全ルールを返す（判定はホスト側が行う）
  - `k2down add RULE [--parent ID]`：1 行ルールを追加し、新しい ID を返す
  - `k2down apply --problem P ID...`：適用したルールを記録する
  - `k2down reject --problem P ID...`：人間が却下したルールを記録する
- MCP ツール（任意）
  - `find_rules(problem)`：問題文に当てはまるルールを返す
  - `add_rule(rule, parent_id?)`：1 行ルールを追加し、新しい ID を返す
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
- 範囲（scope）は store のディレクトリを分けて扱う（`--dir` / `K2DOWN_DIR`）。タグは作らない
- ID は使い回さない。消したルールの番号も再発行しないよう、発行済みの最大番号を rules.json に持つ
- v0.2 でも作らないもの：木構造の探索、推論ループ、マージの自動実行、タグ、一致・矛盾・類似の判定

## v0.3 の範囲（まず安く効くものだけ）
背景は `DESIGN.md` の「v0.3：理由・不可逆・参照切れ」を参照。v0.2 の原則（記録と集計だけ、意味の判定はホスト）は変えない。
- `decide` に任意の `--rationale TEXT`（人が決めた理由。1 行）を足す。`report` の新しいルールの候補に添える
- `escalate` / `decide` に任意の `--irreversible`（取り消せない決断）を足す。`report` に一覧を出す。エージェント向け手順に「不可逆な決断はルールが当たっても人に確認する」と書く
- `report` に「参照切れ」を出す：ルール本文に書かれた ID（`R` + 3 桁以上）のうち、もう無いもの。置き換え済みなら最後の置き換え先を添える（文字列の照合だけ）
- v0.3 でもまだ作らないもの：`review`、`--question`、`--ref`、問題の分類（c1 / c2 / c3）の記録

## データ形式

### rules.json
```json
{
  "version": 1,
  "root": {
    "id": "N000",
    "summary": "全体",
    "children": [
      { "id": "R001", "rule": "外部公開 API の認証は OAuth に統一する" },
      { "id": "R002", "rule": "社内バッチ間の認証はサービスアカウントで行う", "note": "notes/R002.md" }
    ]
  }
}
```
- `children` を持つものが内部ノード（ID は `N` + 3 桁）、`rule` を持つものが葉（ID は `R` + 3 桁）
- ルールは**自然言語 1 行**。改行を含めない
- ID は採番後に変更しない。文言の修正では ID を維持する
- `note` は任意。背景・理由は `notes/<ID>.md` に置く
- `source` は任意（v0.2）。どの決断・どのセッションから生まれたかを 1 行で書く
- `issued` は発行済みの最大番号（v0.2）。例：`"issued": {"N": 1, "R": 31}`。消した ID を再発行しないために使う
- 保存時はキー順・インデント（2 スペース）・末尾改行を固定し、git の差分を安定させる
- 統計は rules.json に**入れない**

### usage.jsonl
1 行 1 イベント。最低限のフィールド：
```json
{"ts": "2026-10-16T09:00:00+09:00", "event": "applied", "rule_id": "R001", "problem": "問題文の要約"}
```
- `event` は `applied`（判定で当てはまった）と `rejected`（人間が却下した）を想定
- 追記のみ。既存行は書き換えない
- v0.2 で増えるイベントとフィールド（`decision` はどのイベントでも任意）：
```json
{"ts": "...", "event": "applied", "rule_id": "R012", "problem": "...", "decision": "D123"}
{"ts": "...", "event": "decided", "decision": "D123", "predicted": "A", "actual": "B", "outcome": "miss"}
{"ts": "...", "event": "escalated", "decision": "D124", "problem": "...", "reason": "conflict", "rule_ids": ["R003", "R017"]}
{"ts": "...", "event": "replaced", "rule_id": "R012", "replaced_by": "R031"}
{"ts": "...", "event": "retired", "rule_id": "R020"}
```
- v0.3 で増えるフィールド（どちらも任意）：`decided` の `rationale`、`escalated` / `decided` の `irreversible`（`true` のときだけ書く）
- `outcome` は `hit`（予測どおり）/ `miss`（外れ）/ `none`（ルールで予測できず人が決めた）
- `rejected`（ルールが当てはまらなかった）と `miss`（当てはまったが予測が外れた）は別に数える

## ディレクトリ構成（目安）
```
src/k2down/
  cli.py     # CLI（本体。標準ライブラリのみ）
  core/      # ルール木の読み書き、判定インターフェース、ログ（通信なし）
  mcp/       # MCP サーバー（任意。sampling で判定）
tests/
```
Jev 等の外部判定アダプタは将来別パッケージにする。このリポジトリのコアには入れない。
