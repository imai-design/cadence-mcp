"""SQLite による記録の保存（標準ライブラリ sqlite3 のみ）。

記録は「追記」を基本とする。既存レコードを書き換えるのは、状態が本質的に1つしか
ないもの（今日の1個の完了、if-then の有効/無効、社会リズムの当日分）に限る。
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ts TEXT NOT NULL,
    mood INTEGER,
    sleep_hours REAL,
    energy INTEGER,
    meds_taken INTEGER,
    stimulants TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS social_rhythm (
    date TEXT PRIMARY KEY,
    wake TEXT, first_contact TEXT, activity_start TEXT, dinner TEXT, bed TEXT,
    updated_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS warning_signs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sign_type TEXT NOT NULL,          -- 'manic' | 'depressive'
    text TEXT NOT NULL,
    actions TEXT,                     -- JSON list（本人の言葉の対処手順）
    created_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    parent_id INTEGER,                -- 分解ステップなら親タスクの id
    step_order INTEGER,               -- 親の中での順番
    is_today_one INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'done'
    created_ts TEXT NOT NULL,
    done_ts TEXT
);
CREATE TABLE IF NOT EXISTS if_then_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,
    action TEXT NOT NULL,
    cue_type TEXT, cue_value TEXT,
    active INTEGER DEFAULT 1,
    created_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    duration_min INTEGER,
    estimate_min INTEGER,
    started_ts TEXT NOT NULL,
    ended_ts TEXT,
    result_note TEXT
);
CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    value TEXT,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS supporters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel TEXT,
    scope TEXT,
    created_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parked_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    context TEXT,
    parked_ts TEXT NOT NULL,
    reviewed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS first_steps (
    date TEXT PRIMARY KEY,            -- 実行する日（予約時の「明日」）
    step TEXT NOT NULL,
    created_ts TEXT NOT NULL,
    consumed INTEGER DEFAULT 0        -- 朝、今やる1個として差し出したら 1
);
CREATE TABLE IF NOT EXISTS day_closes (
    date TEXT PRIMARY KEY,
    closed_ts TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS reentries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    reason TEXT,                      -- 止まっていた理由（本人の言葉/選択肢）
    started_ts TEXT NOT NULL,
    reconnected_ts TEXT,
    result TEXT                       -- sent / partial / not_yet など
);
CREATE TABLE IF NOT EXISTS low_battery_logs (
    date TEXT PRIMARY KEY,
    water INTEGER,
    food INTEGER,
    meds_taken INTEGER,
    contacted TEXT,
    dont_do TEXT,
    note TEXT,
    updated_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS money_snapshots (
    date TEXT PRIMARY KEY,
    stopped_payments TEXT,            -- JSON list
    debt_total REAL,
    income_expected REAL,
    next_item TEXT,
    updated_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_alias TEXT NOT NULL,
    service_type TEXT,
    honnin_ikou TEXT,
    assessment TEXT,
    period_months INTEGER,
    skeleton TEXT,                    -- JSON（計画骨子）
    status TEXT NOT NULL DEFAULT 'draft',  -- 'draft' | 'exported'
    created_ts TEXT NOT NULL,
    exported_ts TEXT,
    export_file TEXT
);
CREATE TABLE IF NOT EXISTS subsidy_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile TEXT,                     -- JSON
    checklist TEXT,                   -- JSON list
    created_ts TEXT NOT NULL
);
"""


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """DB へ接続する。親ディレクトリが無ければ作る。"""
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


@contextmanager
def session(db_path: Optional[Path] = None):
    """接続 → スキーマ初期化 → commit → close をまとめて行う。"""
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows_to_dicts(cur: sqlite3.Cursor) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def one_to_dict(cur: sqlite3.Cursor) -> Optional[Dict[str, Any]]:
    row = cur.fetchone()
    return dict(row) if row else None
