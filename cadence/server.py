"""Cadence MCP サーバー（標準ライブラリのみ・stdio / JSON-RPC 2.0）。

Claude Code / Claude Desktop の MCP クライアントと標準入出力で会話する。
依存パッケージ不要（Python 3.9+ でそのまま動く）。
起動: python3 ~/.cadence/run.py
"""
import json
import sys
from typing import Any, Dict, Optional

from . import __version__, db, tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "cadence", "version": __version__}


def _log(msg: str) -> None:
    # プロトコルは stdout 専用。ログは stderr へ。
    sys.stderr.write(f"[cadence] {msg}\n")
    sys.stderr.flush()


def _result(req_id, result) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tools_list() -> Dict[str, Any]:
    return {"tools": [
        {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
        for name, spec in tools.TOOL_SPECS.items()
    ]}


def handle(req: Dict[str, Any], conn) -> Optional[Dict[str, Any]]:
    """JSON-RPC リクエスト 1件を処理して応答を返す（通知なら None）。"""
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        client_proto = (req.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return _result(req_id, {
            "protocolVersion": client_proto,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # 通知には応答しない

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, _tools_list())

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        out = tools.dispatch(name, args, conn)
        conn.commit()
        return _result(req_id, {
            "content": [{"type": "text", "text": out.get("text", "")}],
            "isError": bool(out.get("_error")),
        })

    if req_id is not None:
        return _error(req_id, -32601, f"Method not found: {method}")
    return None


def main() -> None:
    conn = db.connect()
    db.init_db(conn)
    _log(f"started (v{__version__}). tools={len(tools.TOOL_SPECS)}")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                _log("skip non-JSON line")
                continue
            try:
                resp = handle(req, conn)
            except Exception as exc:  # noqa: BLE001
                _log(f"handler error: {exc}")
                resp = _error(req.get("id"), -32603, f"Internal error: {exc}")
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
