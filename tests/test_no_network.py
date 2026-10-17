"""コアが通信しないことを静的に確認する。"""

import ast
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "k2down"

# 通信に使えるモジュール。コア・サーバーともに import してはならない。
FORBIDDEN = {
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "poplib", "imaplib",
    "telnetlib", "xmlrpc", "socketserver", "asyncio.streams", "webbrowser",
    "requests", "httpx", "httpx2", "aiohttp", "urllib3", "websockets", "grpc",
}


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=lambda p: str(p.relative_to(SRC)))
def test_no_network_imports(path):
    for name in imported_modules(path):
        parts = name.split(".")
        prefixes = {".".join(parts[: i + 1]) for i in range(len(parts))}
        assert not prefixes & FORBIDDEN, f"{path.relative_to(ROOT)} imports {name}"


# CLI と core は標準ライブラリだけで動く（mcp パッケージは MCP サーバー専用）。
STDLIB_ONLY = sorted([*(SRC / "core").rglob("*.py"), SRC / "__init__.py", SRC / "__main__.py", SRC / "cli.py"])


@pytest.mark.parametrize("path", STDLIB_ONLY, ids=lambda p: str(p.relative_to(SRC)))
def test_cli_and_core_import_only_stdlib_and_itself(path):
    import sys

    for name in imported_modules(path):
        top = name.split(".")[0]
        assert top in sys.stdlib_module_names or top in {"k2down", "__future__"}, f"{path.name} imports {name}"
        assert not name.startswith("k2down.mcp"), f"{path.name} imports {name}"


def test_core_has_no_runtime_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == []
