#!/usr/bin/env python3
"""Cadence MCP サーバーの起動ラッパー。

どこから呼ばれても cadence パッケージを見つけられるよう、自身の場所を sys.path に
足してから server.main() を起動する。MCP 登録時はこのファイルを指す:

    claude mcp add cadence -- python3 /path/to/cadence/run.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cadence.server import main  # noqa: E402

if __name__ == "__main__":
    main()
