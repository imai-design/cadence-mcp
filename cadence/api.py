"""AI-facing Cadence API server.

This module exposes the same safe tool registry as the stdio MCP server, but
over localhost HTTP so non-Claude agents can call it too. It stays stdlib-only
and intentionally keeps all medical/safety behavior inside cadence.tools.
"""
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__, config, db, safety, server, signals, tools


MAX_BODY_BYTES = 64 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ApiError(ValueError):
    """A request error that should be returned to the API caller."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _json_schema_ref(name: str) -> Dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def mcp_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": name,
            "description": spec["description"],
            "inputSchema": spec["inputSchema"],
        }
        for name, spec in tools.TOOL_SPECS.items()
    ]


def openai_tools() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["inputSchema"],
            },
        }
        for name, spec in tools.TOOL_SPECS.items()
    ]


def anthropic_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": name,
            "description": spec["description"],
            "input_schema": spec["inputSchema"],
        }
        for name, spec in tools.TOOL_SPECS.items()
    ]


def tool_catalog(fmt: str = "mcp") -> Dict[str, Any]:
    if fmt == "openai":
        return {"format": fmt, "tools": openai_tools()}
    if fmt == "anthropic":
        return {"format": fmt, "tools": anthropic_tools()}
    return {"format": "mcp", "tools": mcp_tools()}


def agent_instructions() -> Dict[str, Any]:
    return {
        "name": "Cadence",
        "purpose": "ADHDと気分の波がある人の、記録・気づき・次の一歩を補助するローカルツール群。",
        "non_goals": [
            "診断しない",
            "薬の量・中止・飲み合わせを判断しない",
            "ストリーク、罰、恥、他者比較で行動を促さない",
            "本人の明示同意なしに支援者へ共有しない",
        ],
        "safety_rules": [
            "どの道具を使うか不明なときは choose_support_mode に相談文を渡し、提案を本人に確認する。",
            "希死念慮・自傷・強い危機サインがあれば route_to_crisis_support を最優先で呼ぶ。",
            "薬をやめたい/減らしたい、用量や診断の相談は主治医へつなぐ。",
            "チェックインは1日30秒・5項目以内を目安に、記録の完璧さを求めない。",
            "大きなタスクは30秒で触れる一歩まで小さくする。",
            "夜の加速時は、思いつきを park_idea へ退避し reserve_first_step で明日の入口を1つだけ作る。",
            "谷の日は low_battery_mode で生活維持の選択肢を最大3つまでに減らす。",
            "お金の不安は money_fog で3つの事実に分けるが、金融助言や借入提案はしない。",
        ],
        "disclaimer": safety.DISCLAIMER,
        "contacts": list(config.CRISIS_CONTACTS_JP),
        "emergency": config.EMERGENCY_JP,
    }


def state_summary(conn) -> Dict[str, Any]:
    today = tools._today()  # noqa: SLF001 - shared timestamp policy for this small local app.
    latest = db.one_to_dict(conn.execute(
        "SELECT id, date, mood, sleep_hours, energy, meds_taken, stimulants, note "
        "FROM checkins ORDER BY date DESC, ts DESC LIMIT 1"
    ))
    current_task = db.one_to_dict(conn.execute(
        "SELECT id, title FROM tasks WHERE is_today_one=1 AND status='open' ORDER BY id LIMIT 1"
    ))
    if current_task is None:
        current_task = db.one_to_dict(conn.execute(
            "SELECT id, title FROM tasks WHERE status='open' "
            "ORDER BY (parent_id IS NULL), step_order, created_ts LIMIT 1"
        ))
    recent_checkins = db.rows_to_dicts(conn.execute(
        "SELECT date, mood, sleep_hours, energy FROM checkins ORDER BY date DESC, ts DESC LIMIT 7"
    ))
    recent_checkins.reverse()
    signs = db.rows_to_dicts(conn.execute("SELECT sign_type, text, actions FROM warning_signs"))
    for sign in signs:
        try:
            sign["actions"] = json.loads(sign.get("actions") or "[]")
        except (TypeError, ValueError):
            sign["actions"] = []
    notices = signals.detect(recent_checkins, signs)
    active_focus = db.one_to_dict(conn.execute(
        "SELECT id, duration_min, started_ts FROM focus_sessions "
        "WHERE ended_ts IS NULL ORDER BY id DESC LIMIT 1"
    ))
    landing = {
        "parked_today": conn.execute(
            "SELECT COUNT(*) AS n FROM parked_ideas WHERE date(parked_ts)=?", (today,)
        ).fetchone()["n"],
        "reserved_first_step": db.one_to_dict(conn.execute(
            "SELECT date, step FROM first_steps WHERE consumed=0 ORDER BY date LIMIT 1"
        )),
        "day_closed": bool(conn.execute(
            "SELECT 1 FROM day_closes WHERE date=? LIMIT 1", (today,)
        ).fetchone()),
    }
    active_reentry = db.one_to_dict(conn.execute(
        "SELECT id, target, reason, started_ts FROM reentries "
        "WHERE reconnected_ts IS NULL ORDER BY id DESC LIMIT 1"
    ))
    low_battery = db.one_to_dict(conn.execute(
        "SELECT date, water, food, meds_taken, contacted, dont_do "
        "FROM low_battery_logs ORDER BY date DESC LIMIT 1"
    ))
    money_fog = db.one_to_dict(conn.execute(
        "SELECT date, next_item FROM money_snapshots ORDER BY date DESC LIMIT 1"
    ))
    counts = conn.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM checkins) AS checkins, "
        "(SELECT COUNT(*) FROM tasks WHERE status='open') AS open_tasks, "
        "(SELECT COUNT(*) FROM achievements WHERE date(ts)=?) AS achievements_today",
        (today,),
    ).fetchone()
    return {
        "date": today,
        "latest_checkin": latest,
        "recent_checkins": recent_checkins,
        "current_task": current_task,
        "notices": notices,
        "active_focus": active_focus,
        "landing": landing,
        "active_reentry": active_reentry,
        "low_battery": low_battery,
        "money_fog": money_fog,
        "counts": dict(counts),
        "disclaimer": safety.DISCLAIMER,
    }


def openapi_spec(base_url: str = "http://127.0.0.1:8787") -> Dict[str, Any]:
    security = [{"CadenceToken": []}]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Cadence AI API",
            "version": __version__,
            "description": (
                "Local-first tools for ADHD and mood-rhythm support. "
                "This is not a diagnostic or medical-treatment API."
            ),
        },
        "servers": [{"url": base_url}],
        "security": security,
        "paths": {
            "/health": {
                "get": {
                    "operationId": "cadenceHealth",
                    "summary": "Check whether the Cadence API is running.",
                    "security": [],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/v1/agent-instructions": {
                "get": {
                    "operationId": "cadenceAgentInstructions",
                    "summary": "Read safety and usage instructions for AI agents.",
                    "responses": {"200": {"description": "Agent instructions"}},
                }
            },
            "/v1/state/summary": {
                "get": {
                    "operationId": "cadenceStateSummary",
                    "summary": "Read a compact local state summary.",
                    "responses": {"200": {"description": "Cadence state summary"}},
                }
            },
            "/v1/tools": {
                "get": {
                    "operationId": "cadenceListTools",
                    "summary": "List Cadence tools. Use ?format=openai or ?format=anthropic if needed.",
                    "parameters": [{
                        "name": "format",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["mcp", "openai", "anthropic"]},
                    }],
                    "responses": {"200": {"description": "Tool definitions"}},
                }
            },
            "/v1/tools/{tool_name}/call": {
                "post": {
                    "operationId": "cadenceCallTool",
                    "summary": "Call one Cadence tool by name.",
                    "parameters": [{
                        "name": "tool_name",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "enum": list(tools.TOOL_SPECS)},
                    }],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": _json_schema_ref("ToolCallRequest")
                            }
                        },
                    },
                    "responses": {"200": {"description": "Tool result"}},
                }
            },
            "/v1/mcp": {
                "post": {
                    "operationId": "cadenceJsonRpcBridge",
                    "summary": "Send JSON-RPC MCP-style messages over HTTP.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"type": ["object", "array"]}}},
                    },
                    "responses": {"200": {"description": "JSON-RPC response"}},
                }
            },
        },
        "components": {
            "securitySchemes": {
                "CadenceToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Cadence-Token",
                    "description": "Required when CADENCE_API_TOKEN is set or the API is exposed beyond localhost.",
                }
            },
            "schemas": {
                "ToolCallRequest": {
                    "type": "object",
                    "properties": {
                        "arguments": {
                            "type": "object",
                            "additionalProperties": True,
                            "description": "Arguments matching the selected tool input schema.",
                        }
                    },
                    "additionalProperties": True,
                }
            },
        },
        "x-cadence-tools": mcp_tools(),
        "x-cadence-agent-instructions": agent_instructions(),
    }


def _extract_tool_name(path: str) -> Optional[str]:
    prefix = "/v1/tools/"
    suffix = "/call"
    if not (path.startswith(prefix) and path.endswith(suffix)):
        return None
    name = path[len(prefix):-len(suffix)]
    return name or None


def _tool_arguments(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "arguments" in payload:
        args = payload.get("arguments") or {}
        if not isinstance(args, dict):
            raise ApiError("arguments must be an object")
        return args
    # Allow direct JSON bodies for lightweight clients.
    return payload


def _handle_mcp_payload(payload: Any, conn):
    if isinstance(payload, list):
        responses = []
        for item in payload:
            if not isinstance(item, dict):
                raise ApiError("JSON-RPC batch items must be objects")
            resp = server.handle(item, conn)
            if resp is not None:
                responses.append(resp)
        conn.commit()
        return responses
    if not isinstance(payload, dict):
        raise ApiError("JSON-RPC payload must be an object or array")
    resp = server.handle(payload, conn)
    conn.commit()
    return resp


def dispatch_api(conn, method: str, path: str, payload: Any = None,
                 query: Optional[Dict[str, List[str]]] = None,
                 base_url: str = "http://127.0.0.1:8787"):
    """Dispatch an AI API request. Used by both HTTP handler and tests."""
    query = query or {}
    payload = payload or {}

    if method == "GET" and path == "/health":
        return {"ok": True, "service": "cadence-api", "version": __version__}
    if method == "GET" and path == "/v1/agent-instructions":
        return agent_instructions()
    if method == "GET" and path == "/v1/tools":
        fmt = (query.get("format") or ["mcp"])[0]
        return tool_catalog(fmt)
    if method == "GET" and path == "/v1/state/summary":
        return state_summary(conn)
    if method == "GET" and path == "/v1/openapi.json":
        return openapi_spec(base_url)

    if method == "POST" and path == "/v1/mcp":
        return _handle_mcp_payload(payload, conn)

    tool_name = _extract_tool_name(path)
    if method == "POST" and tool_name:
        if tool_name not in tools.TOOL_SPECS:
            raise ApiError(f"Unknown tool: {tool_name}", 404)
        if not isinstance(payload, dict):
            raise ApiError("Request body must be a JSON object")
        out = tools.dispatch(tool_name, _tool_arguments(payload), conn)
        conn.commit()
        return {
            "tool": tool_name,
            "is_error": bool(out.get("_error")),
            "content": [{"type": "text", "text": out.get("text", "")}],
            "result": out,
        }

    raise ApiError("Not found", 404)


def _token_from_headers(headers) -> Optional[str]:
    auth = headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ").strip()
    return headers.get("X-Cadence-Token")


def _is_authorized(headers, expected_token: Optional[str]) -> bool:
    if not expected_token:
        return True
    return _token_from_headers(headers) == expected_token


class CadenceApiHandler(BaseHTTPRequestHandler):
    server_version = "CadenceAPI/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[cadence-api] {self.address_string()} {fmt % args}\n")
        sys.stderr.flush()

    @property
    def token(self) -> Optional[str]:
        return getattr(self.server, "cadence_token", None)

    @property
    def base_url(self) -> str:
        return getattr(self.server, "cadence_base_url", "http://127.0.0.1:8787")

    def _json(self, data: Any, status: int = 200):
        body = b"" if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError("Invalid Content-Length") from exc
        if length > MAX_BODY_BYTES:
            raise ApiError("Request body too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("Invalid JSON body") from exc

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        if parsed.path != "/health" and not _is_authorized(self.headers, self.token):
            self._json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            payload = self._read_json() if method == "POST" else None
            with db.session() as conn:
                result = dispatch_api(
                    conn, method, parsed.path, payload, parse_qs(parsed.query), self.base_url)
            if result is None:
                self._json(None, HTTPStatus.NO_CONTENT)
            else:
                self._json(result)
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"Internal error: {type(exc).__name__}"}, 500)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def _requires_token(host: str, token: Optional[str]) -> bool:
    return host not in LOCAL_HOSTS and not token


def serve(host: str = "127.0.0.1", port: int = 8787,
          token: Optional[str] = None, base_url: Optional[str] = None):
    """Run the AI-facing API server until interrupted."""
    token = token if token is not None else os.environ.get("CADENCE_API_TOKEN")
    if _requires_token(host, token):
        raise SystemExit(
            "Refusing to bind beyond localhost without CADENCE_API_TOKEN. "
            "Set a token or use --host 127.0.0.1."
        )
    httpd = ThreadingHTTPServer((host, port), CadenceApiHandler)
    httpd.cadence_token = token
    httpd.cadence_base_url = base_url or f"http://{host}:{port}"
    print(f"Cadence AI API is running at {httpd.cadence_base_url}")
    print("Claude MCP(stdio): python3 /path/to/cadence/run.py")
    print("HTTP tools: GET /v1/tools, POST /v1/tools/{name}/call")
    if token:
        print("Auth: send X-Cadence-Token or Authorization: Bearer <token>")
    else:
        print("Auth: off for localhost-only use")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
