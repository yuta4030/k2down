# CONTRIBUTING

## 開発

```sh
uv run pytest
```

- CLI とコア（`src/k2down/cli.py`、`src/k2down/core/`）は標準ライブラリだけで書く。依存を足さない
- ライブラリは一切通信しない。テストでも通信しない（判定はフェイク判定器で行う）
- 実装時に守ることは [CLAUDE.md](CLAUDE.md)、設計の背景は [DESIGN.md](DESIGN.md)

## 互換性

利用者との約束は [README の「互換性」](README.md#互換性) にある。`tests/test_contract.py` がその約束を確かめる。

- このテストが落ちる変更は、利用者の連携を壊す。マイナー版を上げ、CHANGELOG の「壊れる変更」に書いてから直す
- 出力にキーを足すだけなら壊れる変更ではない。テストにも足しておく

## リリース

1. `pyproject.toml` の `version` と `src/k2down/__init__.py` の `__version__` を上げる（`uv lock` で `uv.lock` も更新）
   - 0.x のうちは、壊れる変更があればマイナー（0.4.0 → 0.5.0）、なければパッチ（0.4.0 → 0.4.1）
2. `CHANGELOG.md` に `## [<版>] - <日付>` の節を書く（テストが、今の版の節があるかを確かめる）
3. PR をマージする。main の版にまだタグがなければ、CI（`.github/workflows/release.yml`）が `v<版>` のタグと GitHub Release を作る。Release の本文は CHANGELOG のその版の節
