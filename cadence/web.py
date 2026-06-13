"""Cadence Now: localhost-only web API and static PWA server.

The web UI is intentionally thin. It reuses Cadence's SQLite store, safety
checks, and domain tools instead of creating a second source of truth.
"""
import json
import mimetypes
import re
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from . import config, db, safety, signals, tools


STATIC_DIR = config.CADENCE_HOME / "web"
MAX_BODY_BYTES = 32 * 1024
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ApiError(ValueError):
    """A user-fixable API request error."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _one(cur) -> Optional[Dict[str, Any]]:
    row = cur.fetchone()
    return dict(row) if row else None


def _current_task(conn) -> Optional[Dict[str, Any]]:
    current = _one(conn.execute(
        "SELECT id, title FROM tasks WHERE is_today_one=1 AND status='open' ORDER BY id LIMIT 1"
    ))
    if current:
        return current
    return _one(conn.execute(
        "SELECT id, title FROM tasks WHERE status='open' "
        "ORDER BY (parent_id IS NULL), step_order, created_ts LIMIT 1"
    ))


def dashboard(conn) -> Dict[str, Any]:
    """Return the compact state needed to render the home screen."""
    today = _today()
    latest = _one(conn.execute(
        "SELECT id, date, mood, sleep_hours, energy, meds_taken, note "
        "FROM checkins WHERE date=? ORDER BY id DESC LIMIT 1", (today,)
    ))
    rhythm = _one(conn.execute(
        "SELECT date, wake, first_contact, activity_start, dinner, bed "
        "FROM social_rhythm WHERE date=?", (today,)
    ))
    recent = db.rows_to_dicts(conn.execute(
        "SELECT c.date, c.mood, c.sleep_hours, c.energy FROM checkins c "
        "JOIN (SELECT date, MAX(id) AS max_id FROM checkins GROUP BY date) x "
        "ON c.id=x.max_id ORDER BY c.date DESC LIMIT 7"
    ))
    recent.reverse()

    all_checkins = db.rows_to_dicts(conn.execute(
        "SELECT date, mood, sleep_hours, energy FROM checkins ORDER BY date, ts"
    ))
    sign_rows = db.rows_to_dicts(conn.execute(
        "SELECT sign_type, text, actions FROM warning_signs ORDER BY id"
    ))
    for sign in sign_rows:
        try:
            sign["actions"] = json.loads(sign.get("actions") or "[]")
        except (TypeError, ValueError):
            sign["actions"] = []

    active_focus = _one(conn.execute(
        "SELECT id, duration_min, started_ts FROM focus_sessions "
        "WHERE ended_ts IS NULL ORDER BY id DESC LIMIT 1"
    ))
    achievements = conn.execute(
        "SELECT COUNT(*) AS n FROM achievements WHERE date(ts)=?", (today,)
    ).fetchone()["n"]

    parked_today = conn.execute(
        "SELECT COUNT(*) AS n FROM parked_ideas WHERE date(parked_ts)=?", (today,)
    ).fetchone()["n"]

    tomorrow_row = conn.execute(
        "SELECT step FROM first_steps "
        "WHERE date > ? AND consumed=0 ORDER BY date LIMIT 1", (today,)
    ).fetchone()
    reserved_first_step = tomorrow_row["step"] if tomorrow_row else None

    day_closed = conn.execute(
        "SELECT 1 FROM day_closes WHERE date=? LIMIT 1", (today,)
    ).fetchone() is not None

    low_battery = _one(conn.execute(
        "SELECT water, food, meds_taken, contacted, dont_do, note "
        "FROM low_battery_logs WHERE date=?", (today,)
    ))

    return {
        "date": today,
        "latest_checkin": latest,
        "today_rhythm": rhythm,
        "recent_checkins": recent,
        "current_task": _current_task(conn),
        "notices": signals.detect(all_checkins, sign_rows),
        "active_focus": active_focus,
        "today_achievements": achievements,
        "contacts": list(config.CRISIS_CONTACTS_JP),
        "emergency": config.EMERGENCY_JP,
        "disclaimer": safety.DISCLAIMER,
        "parked_today": parked_today,
        "reserved_first_step": reserved_first_step,
        "day_closed": day_closed,
        "low_battery": low_battery,
    }


def _number(value, name: str, low: float, high: float, integer: bool = False):
    if value is None or value == "":
        return None
    try:
        parsed = int(value) if integer else float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{name}の値を確認してください。") from exc
    if not low <= parsed <= high:
        raise ApiError(f"{name}は {low}〜{high} の範囲で入力してください。")
    return parsed


def _text(value, name: str, max_length: int, required: bool = False) -> Optional[str]:
    if value is None:
        value = ""
    value = str(value).strip()
    if required and not value:
        raise ApiError(f"{name}を一言入れてください。")
    if len(value) > max_length:
        raise ApiError(f"{name}は{max_length}文字以内にしてください。")
    return value or None


def dispatch_api(conn, method: str, path: str, payload: Optional[Dict[str, Any]] = None):
    """Dispatch one JSON API request. Kept separate for fast unit tests."""
    payload = payload or {}
    if method == "GET" and path == "/api/dashboard":
        return dashboard(conn)

    if method != "POST":
        raise ApiError("見つかりませんでした。", 404)

    if path == "/api/checkin":
        note = _text(payload.get("note"), "メモ", 1000)
        args = {
            "mood": _number(payload.get("mood"), "気分", -5, 5, integer=True),
            "sleep_hours": _number(payload.get("sleep_hours"), "睡眠時間", 0, 24),
            "energy": _number(payload.get("energy"), "エネルギー", 0, 5, integer=True),
            "note": note,
        }
        if "meds_taken" in payload and payload["meds_taken"] is not None:
            args["meds_taken"] = bool(payload["meds_taken"])
        result = tools.log_daily_checkin(conn, args)
        return {
            "result": result,
            "needs_support": safety.detect_crisis(note or ""),
            "needs_medical_redirect": (
                safety.detect_med_discontinuation(note or "")
                or safety.detect_medical_advice_request(note or "")
            ),
            "dashboard": dashboard(conn),
        }

    if path == "/api/task":
        title = _text(payload.get("title"), "今やる一歩", 160, required=True)
        cur = conn.execute(
            "INSERT INTO tasks (title, is_today_one, status, created_ts) VALUES (?, 0, 'open', ?)",
            (title, _now_iso()),
        )
        if not conn.execute(
            "SELECT 1 FROM tasks WHERE is_today_one=1 AND status='open' LIMIT 1"
        ).fetchone():
            conn.execute("UPDATE tasks SET is_today_one=1 WHERE id=?", (cur.lastrowid,))
        return {"message": "一歩を置きました。今はこれだけ見れば大丈夫です。",
                "dashboard": dashboard(conn)}

    if path == "/api/task/complete":
        task_id = payload.get("task_id")
        task = None
        if task_id is not None:
            task = conn.execute(
                "SELECT * FROM tasks WHERE id=? AND status='open'", (task_id,)
            ).fetchone()
        if task is None:
            current = _current_task(conn)
            if current:
                task = conn.execute("SELECT * FROM tasks WHERE id=?", (current["id"],)).fetchone()
        if task:
            conn.execute(
                "UPDATE tasks SET status='done', done_ts=?, is_today_one=0 WHERE id=?",
                (_now_iso(), task["id"]),
            )
            conn.execute(
                "INSERT INTO achievements (event_type, value, ts) VALUES ('task_done', ?, ?)",
                (task["title"], _now_iso()),
            )
        next_task = _current_task(conn)
        if next_task:
            conn.execute("UPDATE tasks SET is_today_one=1 WHERE id=?", (next_task["id"],))
        return {"message": "ここまでを前進として残しました。", "dashboard": dashboard(conn)}

    if path == "/api/rhythm":
        args: Dict[str, Any] = {}
        for key in config.RHYTHM_ANCHORS:
            value = payload.get(key)
            if value not in (None, ""):
                if not _TIME_RE.match(str(value)):
                    raise ApiError("時刻は HH:MM 形式で入力してください。")
                args[key] = str(value)
        if not args:
            raise ApiError("覚えている時刻を1つだけ入れてください。")
        result = tools.log_social_rhythm(conn, args)
        return {"result": result, "dashboard": dashboard(conn)}

    if path == "/api/focus/start":
        duration = _number(payload.get("duration_min") or 5, "時間", 1, 120, integer=True)
        current = _current_task(conn)
        result = tools.start_focus_timer(conn, {
            "duration_min": duration,
            "task_id": current["id"] if current else None,
        })
        return {"result": result, "dashboard": dashboard(conn)}

    if path == "/api/focus/end":
        note = _text(payload.get("result_note"), "できたこと", 300) or "タイムボックスを閉じた"
        result = tools.start_focus_timer(conn, {
            "session_id": payload.get("session_id"),
            "result_note": note,
        })
        return {"result": result, "dashboard": dashboard(conn)}

    if path == "/api/idea":
        text = _text(payload.get("text"), "思いつき", 500, required=True)
        context = _text(payload.get("context"), "補足", 200)
        result = tools.park_idea(conn, {"text": text, "context": context})
        return {"result": result, "dashboard": dashboard(conn)}

    if path == "/api/first-step":
        step = _text(payload.get("step"), "最初の一歩", 160, required=True)
        result = tools.reserve_first_step(conn, {"step": step})
        return {"result": result, "dashboard": dashboard(conn)}

    if path == "/api/wind-down":
        close = bool(payload.get("close")) if "close" in payload else False
        note = _text(payload.get("note"), "一言", 500)
        args: Dict[str, Any] = {}
        if close:
            args["close"] = True
        if note:
            args["note"] = note
        result = tools.start_wind_down(conn, args)
        return {"result": result, "dashboard": dashboard(conn)}

    if path == "/api/low-battery":
        args: Dict[str, Any] = {}
        for key in ("water", "food", "meds_taken"):
            if key in payload and payload[key] is not None:
                args[key] = bool(payload[key])
        contacted = _text(payload.get("contacted"), "連絡した人", 200)
        if contacted:
            args["contacted"] = contacted
        dont_do = _text(payload.get("dont_do"), "今日やらないこと", 200)
        if dont_do:
            args["dont_do"] = dont_do
        note = _text(payload.get("note"), "メモ", 500)
        if note:
            args["note"] = note
        result = tools.low_battery_mode(conn, args)
        return {"result": result, "dashboard": dashboard(conn)}

    raise ApiError("見つかりませんでした。", 404)


class CadenceHandler(BaseHTTPRequestHandler):
    server_version = "CadenceNow/0.1"

    def log_message(self, fmt, *args):
        print(f"[cadence-now] {self.address_string()} {fmt % args}")

    def _json(self, data: Dict[str, Any], status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError("リクエストを読み取れませんでした。") from exc
        if length > MAX_BODY_BYTES:
            raise ApiError("入力が大きすぎます。", 413)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("入力を読み取れませんでした。") from exc
        if not isinstance(data, dict):
            raise ApiError("入力形式を確認してください。")
        return data

    def _api(self, method: str, path: str):
        try:
            payload = self._read_json() if method == "POST" else None
            with db.session() as conn:
                result = dispatch_api(conn, method, path, payload)
            self._json(result)
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"うまく処理できませんでした（{type(exc).__name__}）。"}, 500)

    def _static(self, path: str):
        relative = "index.html" if path == "/" else path.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in candidate.parents and candidate != STATIC_DIR.resolve():
            self.send_error(404)
            return
        if not candidate.is_file():
            candidate = STATIC_DIR / "index.html"
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self._api("GET", path)
        else:
            self._static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self._api("POST", path)
        else:
            self.send_error(404)


def serve(host: str = "127.0.0.1", port: int = 8765):
    """Run the localhost-only web server until interrupted."""
    server = ThreadingHTTPServer((host, port), CadenceHandler)
    print(f"Cadence Now is running at http://{host}:{port}")
    print("入力はこのMacの中だけに保存されます。終了: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
