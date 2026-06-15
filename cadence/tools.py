"""Cadence の 24 ツール（ロジック層）。MCP には依存しない純粋な関数群。

各ツールは (conn, args) を受け取り、{"text": 利用者に伝える文, ...} を返す。
server.py がこのレジストリを JSON-RPC(stdio) で公開する。知能（分割文の生成や
寄り添いの言葉選び）は呼び出し側の Claude が担い、ここは保存・集計・安全に徹する。
"""
import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from . import config, copy_guard, rhythm, safety, signals


# ---- 小さなユーティリティ ----

def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_hm() -> str:
    return datetime.now().strftime("%H:%M")


def _now_min() -> int:
    now = datetime.now()
    return now.hour * 60 + now.minute


def _min_to_hm(minutes: Optional[int]) -> Optional[str]:
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _today_ja() -> str:
    """事業所の書類向けに、日本語の自然な日付（例: 2026年6月13日）を返す。"""
    d = date.today()
    return f"{d.year}年{d.month}月{d.day}日"


def _ok(text: str, **data) -> Dict[str, Any]:
    """ツールの戻り値。Cadence 生成文は copy_guard を通し、違反は警告として残す。"""
    violations = copy_guard.check_copy(text)
    result: Dict[str, Any] = {"text": text}
    if violations:
        result["_copy_warnings"] = violations
    result.update(data)
    return result


def _safety_prefix(text: str) -> Optional[str]:
    """ユーザーの自由記述に危機/減薬/医療判断の語があれば、前置きを返す。"""
    if not text:
        return None
    if safety.detect_crisis(text):
        return safety.crisis_message()
    if safety.detect_med_discontinuation(text):
        return safety.med_nudge_message()
    if safety.detect_medical_advice_request(text):
        return safety.medical_advice_redirect()
    return None


# ---- 1. 記録: 気分チェックイン ----

def log_daily_checkin(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    d = args.get("date") or _today()
    mood = args.get("mood")
    sleep_hours = args.get("sleep_hours")
    energy = args.get("energy")
    meds_taken = args.get("meds_taken")
    stimulants = args.get("stimulants")
    note = args.get("note")

    conn.execute(
        "INSERT INTO checkins (date, ts, mood, sleep_hours, energy, meds_taken, stimulants, note)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (d, _now_iso(), mood, sleep_hours, energy,
         (None if meds_taken is None else int(bool(meds_taken))), stimulants, note),
    )

    # メンタル日記に「人が読める正本」を1行追記
    parts: List[str] = []
    if mood is not None:
        parts.append(f"気分 {mood:+d}")
    if sleep_hours is not None:
        parts.append(f"睡眠 {sleep_hours}h")
    if energy is not None:
        parts.append(f"エネルギー {energy}/5")
    if meds_taken is not None:
        parts.append("服薬済み" if meds_taken else "服薬まだ")
    if stimulants:
        parts.append(f"刺激物 {stimulants}")
    summary = "（チェックイン）" + "／".join(parts) if parts else "（チェックイン）"
    if note:
        summary += f" — {note}"
    from . import vault
    diary = vault.append_checkin(d, summary)

    # 中立のエコーバック（褒めない・点数評価しない）
    echoed = "、".join(parts) if parts else "今日のチェックイン"
    text = f"記録しました：{echoed}。"
    if diary:
        text += "メンタル日記にも残しています。"

    prefix = _safety_prefix(note or "")
    if prefix:
        text = prefix + "\n\n" + text
    text += "\n" + safety.DISCLAIMER
    return _ok(text, saved_to=diary, date=d)


# ---- 2. 記録: 社会リズム（5つの定点） ----

def log_social_rhythm(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    d = args.get("date") or _today()
    vals = {a: args.get(a) for a in config.RHYTHM_ANCHORS}

    existing = conn.execute("SELECT * FROM social_rhythm WHERE date=?", (d,)).fetchone()
    if existing:
        merged = {a: (vals[a] if vals[a] is not None else existing[a]) for a in config.RHYTHM_ANCHORS}
        conn.execute(
            "UPDATE social_rhythm SET wake=?, first_contact=?, activity_start=?, dinner=?, bed=?, updated_ts=? WHERE date=?",
            (merged["wake"], merged["first_contact"], merged["activity_start"],
             merged["dinner"], merged["bed"], _now_iso(), d),
        )
    else:
        conn.execute(
            "INSERT INTO social_rhythm (date, wake, first_contact, activity_start, dinner, bed, updated_ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (d, vals["wake"], vals["first_contact"], vals["activity_start"],
             vals["dinner"], vals["bed"], _now_iso()),
        )

    recorded = [config.RHYTHM_ANCHOR_LABELS[a] for a in config.RHYTHM_ANCHORS if vals[a]]
    missing = [config.RHYTHM_ANCHOR_LABELS[a] for a in config.RHYTHM_ANCHORS
               if not (vals[a] or (existing and existing[a]))]
    text = f"{d} のリズムを記録しました（{('・'.join(recorded)) or '更新なし'}）。"
    if missing:
        text += f" まだ空いているのは：{('・'.join(missing))}。覚えていたら足してください（無理に全部埋めなくて大丈夫）。"
    return _ok(text, date=d)


# ---- 3. 気づき: 社会リズムの規則性 ----

def track_rhythm_regularity(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    window = args.get("window_days") or config.RHYTHM_DEFAULT_WINDOW_DAYS
    rows = conn.execute("SELECT * FROM social_rhythm ORDER BY date").fetchall()
    records = [dict(r) for r in rows]
    if len(records) < 2:
        return _ok("規則性を出すには、あと数日ぶんのリズム記録があると見えてきます。"
                   "今は記録をためる時期。焦らなくて大丈夫です。")

    res = rhythm.regularity(records, window_days=window)
    score = res["score_0_7"]
    text = f"直近{res['days_counted']}日の社会リズムの規則性は 7点満点で約 {score} 点です。"
    if res["shakiest"]:
        anchor = res["per_anchor"][res["shakiest"]]
        text += (f" いちばんブレているのは「{anchor['label']}」（ばらつき約{anchor['spread_min']}分）。"
                 "ここを少し一定にできると、体内時計が整いやすいと言われています。")
    text += " ※これは気づきのためで、診断や治療判断ではありません。"
    return _ok(text, regularity=res)


# ---- 4. 行動の足場 / 双極: アクションプラン登録 ----

def build_action_plan(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    signs_in = args.get("signs") or []
    saved = 0
    for s in signs_in:
        sign_type = s.get("type") or s.get("sign_type")
        text = s.get("text")
        actions = s.get("actions") or []
        if sign_type not in ("manic", "depressive") or not text:
            continue
        conn.execute(
            "INSERT INTO warning_signs (sign_type, text, actions, created_ts) VALUES (?,?,?,?)",
            (sign_type, text, json.dumps(actions, ensure_ascii=False), _now_iso()),
        )
        saved += 1

    text = f"早期サインを {saved} 件、あなたの言葉で登録しました。サインが出たとき、ここに書いた対処をそのまま出せます。"
    if args.get("show_depressive_examples"):
        text += ("\n（落ち込み側のサインは、上がる側ほどはっきり捕まえにくいことが知られています。"
                 "例：朝起きられない・連絡を返せなくなる・楽しめない、など。"
                 "これは例示なので、あなた自身の感覚で言葉を選んでください。）")
    return _ok(text, saved=saved)


# ---- 5. 気づき / 双極: 早期警告サインの検知 ----

def detect_early_warning(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    lookback = args.get("lookback_days") or config.EARLY_WARNING_LOOKBACK_DAYS
    checkins = [dict(r) for r in conn.execute(
        "SELECT * FROM checkins ORDER BY date, ts").fetchall()]
    signs = [dict(r) for r in conn.execute("SELECT * FROM warning_signs").fetchall()]
    for s in signs:
        try:
            s["actions"] = json.loads(s.get("actions") or "[]")
        except (ValueError, TypeError):
            s["actions"] = []

    notices = signals.detect(checkins, signs, lookback_days=lookback)
    if not notices:
        return _ok("いまのところ、特に気をつけるサインは出ていません。"
                   "気づいたことがあれば、いつでも記録してください。")

    lines = ["いくつか気づいたことがあります（断定ではなく、気づきです）：", ""]
    for n in notices:
        lines.append(f"・{n['message']}")
        for a in n.get("actions", []):
            lines.append(f"    └ あなたが決めていた対処：{a}")
    lines.append("")
    lines.append("不安にさせるためではありません。早めに気づけると、波は小さくできます。"
                 "気になるときは主治医にも相談してみてください。")
    text = "\n".join(lines)
    return _ok(text, notices=notices)


# ---- 6. 行動の足場 / ADHD: タスク分割 ----

def break_down_task(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    title = (args.get("task") or "").strip()
    if not title:
        return _ok("分けたいことを一言ください。どんなに小さくしてもいい前提で受け取ります。")
    steps = args.get("steps") or []
    blocked = args.get("blocked")

    cur = conn.execute(
        "INSERT INTO tasks (title, created_ts, status) VALUES (?,?, 'open')",
        (title, _now_iso()),
    )
    parent_id = cur.lastrowid
    for i, step in enumerate(steps):
        conn.execute(
            "INSERT INTO tasks (title, parent_id, step_order, created_ts, status) VALUES (?,?,?,?, 'open')",
            (step, parent_id, i, _now_iso()),
        )

    if steps:
        text = (f"「{title}」を {len(steps)} 個のステップに分けて保存しました。"
                f"最初の一歩は「{steps[0]}」。これだけ見えれば十分です。")
    elif blocked:
        text = (f"「{title}」、まだ一歩が大きいのかもしれません。"
                "“それの、いちばん最初の30秒で終わる部分”はどこですか？そこまで小さくして大丈夫です。")
    else:
        text = (f"「{title}」を受け取りました。これを“今すぐ30秒で着手できる最初の一歩”に分けます。"
                "（Claude が一歩を提案して、steps として登録します。）")
    return _ok(text, parent_id=parent_id, step_count=len(steps))


# ---- 7. 行動の足場 / ADHD: 今やる1個 ----

def list_today_one_thing(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    if args.get("complete_current"):
        current = conn.execute(
            "SELECT * FROM tasks WHERE is_today_one=1 AND status='open' ORDER BY id LIMIT 1").fetchone()
        if current:
            conn.execute("UPDATE tasks SET status='done', done_ts=?, is_today_one=0 WHERE id=?",
                         (_now_iso(), current["id"]))
            conn.execute("INSERT INTO achievements (event_type, value, ts) VALUES ('task_done', ?, ?)",
                         (current["title"], _now_iso()))

    # 次の1個を選ぶ（指定があればそれ、なければ最も古い open。分割ステップを優先）
    conn.execute("UPDATE tasks SET is_today_one=0 WHERE is_today_one=1")
    task_id = args.get("task_id")

    # 前夜に予約した「明日の最初の一歩」があれば、何より先に差し出す（Landing 連携）
    if not task_id:
        reserved = conn.execute(
            "SELECT * FROM first_steps WHERE date=? AND consumed=0", (_today(),)).fetchone()
        if reserved:
            cur = conn.execute(
                "INSERT INTO tasks (title, created_ts, status, is_today_one) VALUES (?,?, 'open', 1)",
                (reserved["step"], _now_iso()),
            )
            conn.execute("UPDATE first_steps SET consumed=1 WHERE date=?", (_today(),))
            text = (f"昨日のあなたが予約しておいた最初の一歩です：\n\n   ▶ {reserved['step']}\n\n"
                    "これ1つだけで大丈夫。終わったら complete_current で次へ。終わらなくても大丈夫です。")
            return _ok(text, task_id=cur.lastrowid, title=reserved["step"], reserved=True)

    if task_id:
        nxt = conn.execute("SELECT * FROM tasks WHERE id=? AND status='open'", (task_id,)).fetchone()
    else:
        nxt = conn.execute(
            "SELECT * FROM tasks WHERE status='open' "
            "ORDER BY (parent_id IS NULL), step_order, created_ts LIMIT 1").fetchone()

    if not nxt:
        return _ok("今やる1個は空っぽです。やることが浮かんだら break_down_task で1つ入れましょう。"
                   "何も無いなら、それは休んでいい合図かもしれません。")

    conn.execute("UPDATE tasks SET is_today_one=1 WHERE id=?", (nxt["id"],))
    text = f"いま向き合うのは、これ1つだけ：\n\n   ▶ {nxt['title']}\n\n"
    text += "ほかは隠しておきます。終わったら complete_current で次へ。終わらなくても大丈夫です。"
    return _ok(text, task_id=nxt["id"], title=nxt["title"])


# ---- 8. 行動の足場: if-then プラン ----

def create_if_then_plan(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    trigger = (args.get("trigger") or "").strip()
    action = (args.get("action") or "").strip()
    if not trigger or not action:
        return _ok("「もし〈いつ・どこで・何のあとに〉→〈この行動をする〉」の形で一言ください。")

    active = conn.execute("SELECT COUNT(*) AS n FROM if_then_plans WHERE active=1").fetchone()["n"]
    if active >= config.MAX_ACTIVE_IF_THEN:
        return _ok(f"いま有効な if-then が {active} 個あります。絞るほど効くので、"
                   "新しく足すなら、どれか1つを“おやすみ”にしてからにしましょう。", needs_pruning=True)

    conn.execute(
        "INSERT INTO if_then_plans (trigger, action, cue_type, cue_value, active, created_ts) VALUES (?,?,?,?,1,?)",
        (trigger, action, args.get("cue_type"), args.get("cue_value"), _now_iso()),
    )
    text = (f"登録しました：『もし{trigger} → {action}』。\n"
            "いちど声に出して読んでみてください（1回でいい）。書くだけより、ぐっと発動しやすくなります。")
    return _ok(text)


# ---- 9. 行動の足場 / ADHD: フォーカスタイマー ----

def start_focus_timer(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    result_note = args.get("result_note")
    session_id = args.get("session_id")

    # 終了モード: result_note があれば、対象セッションを締める
    if result_note is not None:
        if session_id:
            sess = conn.execute("SELECT * FROM focus_sessions WHERE id=?", (session_id,)).fetchone()
        else:
            sess = conn.execute("SELECT * FROM focus_sessions WHERE ended_ts IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if not sess:
            return _ok("締めるタイマーが見つかりませんでした。新しく始めるなら duration_min を指定してください。")
        conn.execute("UPDATE focus_sessions SET ended_ts=?, result_note=? WHERE id=?",
                     (_now_iso(), result_note, sess["id"]))
        conn.execute("INSERT INTO achievements (event_type, value, ts) VALUES ('focus_done', ?, ?)",
                     (result_note, _now_iso()))
        return _ok(f"おつかれさまでした。できたこと：「{result_note}」。"
                   "1コマ進んだ事実だけ受け取っておきます。")

    # 開始モード
    duration = args.get("duration_min") or config.DEFAULT_FOCUS_MIN
    estimate = args.get("estimate_min")
    mode = args.get("body_double_mode") or "off"
    cur = conn.execute(
        "INSERT INTO focus_sessions (task_id, duration_min, estimate_min, started_ts) VALUES (?,?,?,?)",
        (args.get("task_id"), duration, estimate, _now_iso()),
    )
    text = f"{duration}分のタイムボックスを始めます。終わりが来るまで、この1コマだけ。"
    if mode == "ai":
        text += "\n私もここにいます。区切りがついたら『何ができたか』を一言だけ教えてください（できなくてもOK）。"
    else:
        text += "\n区切りがついたら result_note で『何ができたか』を一言。ひとりでも回せる作りです。"
    return _ok(text, session_id=cur.lastrowid, duration_min=duration)


# ---- 10. 気づき: 達成の可視化（採点しない・他者比較しない） ----

def track_achievement(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    event_type = args.get("event_type")
    if event_type:
        conn.execute("INSERT INTO achievements (event_type, value, ts) VALUES (?,?,?)",
                     (event_type, args.get("value"), _now_iso()))

    total = conn.execute("SELECT COUNT(*) AS n FROM achievements").fetchone()["n"]
    last7 = conn.execute(
        "SELECT COUNT(*) AS n FROM achievements WHERE ts >= datetime('now','-7 days')").fetchone()["n"]
    text = (f"これまでの“前に進んだ”記録は {total} 件、ここ7日では {last7} 件です。"
            "良し悪しは測りません。過去のあなたとだけ比べた、ただの前進の足あとです。")
    text += "\n次の小さな一歩を1つだけ、よかったら list_today_one_thing で出しましょう。"
    return _ok(text, total=total, last_7_days=last7)


# ---- 11. 共有: 支援者へ（オプトイン必須・実送信はしない） ----

def share_summary_with_supporter(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    if not args.get("consent"):
        return _ok("共有は、あなたが『はい、共有します』と明示したときだけ行います。"
                   "consent を立ててもう一度呼んでください。勝手に誰かへ送ることは絶対にありません。")

    days = args.get("days") or 7
    checkins = [dict(r) for r in conn.execute(
        "SELECT date, mood, sleep_hours, energy, meds_taken FROM checkins "
        "WHERE date >= date('now', ?) ORDER BY date", (f"-{days} days",)).fetchall()]

    fmt = args.get("format") or "message"
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["date", "mood", "sleep_hours", "energy", "meds_taken"])
        for c in checkins:
            writer.writerow([c["date"], c["mood"], c["sleep_hours"], c["energy"], c["meds_taken"]])
        body = buf.getvalue()
    else:
        moods = [c["mood"] for c in checkins if c["mood"] is not None]
        avg = round(sum(moods) / len(moods), 1) if moods else "—"
        body = (f"直近{days}日のチェックイン {len(checkins)}件。気分の平均 {avg}（-5〜+5）。"
                "詳しくは本人と一緒にご覧ください。")

    recipient = args.get("recipient") or "（宛先未指定）"
    text = ("以下は共有内容の“プレビュー”です。送信はあなたの最終確認後にだけ行います"
            "（このツールは自動送信しません）。\n\n"
            f"宛先：{recipient}\n----\n{body}\n----\n"
            "評価のためでなく、味方を増やすための共有です。")
    return _ok(text, preview=body, recipient=recipient)


# ---- 12. 安全ハブ: 危機時の専門窓口 ----

def route_to_crisis_support(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    return _ok(safety.crisis_message())


# ---- 13. Landing: 思いつきの退避箱（失わない保証） ----

def park_idea(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    idea = (args.get("text") or "").strip()
    if not idea:
        return _ok("退避させたい思いつきを一言ください。書きかけ・断片で大丈夫です。")
    context = args.get("context")

    conn.execute(
        "INSERT INTO parked_ideas (text, context, parked_ts) VALUES (?,?,?)",
        (idea, context, _now_iso()),
    )
    from . import vault
    line = idea if not context else f"{idea}（{context}）"
    inbox = vault.append_parked_idea(_today(), line)

    tonight = conn.execute(
        "SELECT COUNT(*) AS n FROM parked_ideas WHERE date(parked_ts)=?", (_today(),)).fetchone()["n"]
    text = (f"退避箱に入れました：「{idea}」。消えません。明日のあなたがいつでも拾えます。\n"
            f"今日の退避は {tonight} 件。出し切ったら、今夜はもう進めなくて大丈夫です。")

    prefix = _safety_prefix(idea)
    if prefix:
        text = prefix + "\n\n" + text
    return _ok(text, saved_to=inbox, today_count=tonight)


# ---- 14. Landing: 明日の最初の一歩を1つだけ予約 ----

def reserve_first_step(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    step = (args.get("step") or "").strip()
    if not step:
        return _ok("明日の最初の一歩を一言ください。30秒で着手できる小ささが目安です"
                   "（例：ファイルを開くだけ）。")
    prefix = _safety_prefix(step)
    if prefix:
        return _ok(prefix)
    target = args.get("date") or (date.today() + timedelta(days=1)).isoformat()

    existing = conn.execute("SELECT step FROM first_steps WHERE date=?", (target,)).fetchone()
    conn.execute(
        "INSERT INTO first_steps (date, step, created_ts, consumed) VALUES (?,?,?,0) "
        "ON CONFLICT(date) DO UPDATE SET step=excluded.step, created_ts=excluded.created_ts, consumed=0",
        (target, step, _now_iso()),
    )

    if existing and existing["step"] != step:
        text = (f"{target} の最初の一歩を入れ替えました：「{existing['step']}」→「{step}」。"
                "予約は常に1つだけ。これで明日の入口は決まりました。")
    else:
        text = (f"{target} の最初の一歩を予約しました：「{step}」。\n"
                "明日の朝、こちらから差し出します。今夜はもう決めなくて大丈夫です。")
    return _ok(text, date=target, step=step)


# ---- 15. Landing: 夜の着地手順（やめても失わない確認 → 閉じる） ----

def start_wind_down(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    today = _today()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    parked = conn.execute(
        "SELECT COUNT(*) AS n FROM parked_ideas WHERE date(parked_ts)=?", (today,)).fetchone()["n"]
    reserved = conn.execute(
        "SELECT step FROM first_steps WHERE date=? AND consumed=0", (tomorrow,)).fetchone()
    open_focus = conn.execute(
        "SELECT id FROM focus_sessions WHERE ended_ts IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    bed_row = conn.execute(
        "SELECT bed FROM social_rhythm WHERE bed IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    bed_anchor = bed_row["bed"] if bed_row else config.DEFAULT_BED_ANCHOR

    # 締めモード：今日はここまで、を記録する
    if args.get("close"):
        note = args.get("note") or ""
        prefix = _safety_prefix(note)
        if prefix:
            return _ok(prefix)
        conn.execute(
            "INSERT INTO day_closes (date, closed_ts, note) VALUES (?,?,?) "
            "ON CONFLICT(date) DO UPDATE SET closed_ts=excluded.closed_ts, note=excluded.note",
            (today, _now_iso(), note or None),
        )
        conn.execute("INSERT INTO achievements (event_type, value, ts) VALUES ('day_landed', ?, ?)",
                     (note or "今日を閉じた", _now_iso()))
        text = "今日はここまで。閉じたことも、ひとつの前進として残しました。\n"
        if parked:
            text += f"退避箱に {parked} 件、ちゃんと残っています。消えません。\n"
        if reserved:
            text += f"明日の入口は「{reserved['step']}」。もう決まっています。\n"
        text += "おやすみなさい。続きは明日のあなたに任せて大丈夫です。"
        return _ok(text, closed=True)

    # 状況確認モード：着地に必要なものが揃っているかを並べる
    lines = [f"着地を始めます。いまの状態（就寝アンカー {bed_anchor}）：", ""]
    lines.append(f"・退避箱：今日 {parked} 件" + ("（思いつきは失われません）" if parked else "（頭に残っているものがあれば park_idea へ）"))
    if reserved:
        lines.append(f"・明日の最初の一歩：予約済み「{reserved['step']}」")
    else:
        lines.append("・明日の最初の一歩：まだ空席（reserve_first_step で1つだけ予約できます）")
    if open_focus:
        lines.append("・開きっぱなしのタイムボックスが1つあります。start_focus_timer に一言入れて閉じられます")
    lines.append("")
    lines.append("着地の手順（3つだけ）：")
    for i, s in enumerate(config.WIND_DOWN_STEPS, 1):
        lines.append(f"{i}. {s}")
    lines.append("")
    lines.append("全部できなくても着地は成立します。閉じるときは close を立てて呼んでください。")

    # 夜の加速への控えめな気づき（断定しない）
    latest = conn.execute(
        "SELECT mood, sleep_hours FROM checkins ORDER BY date DESC, ts DESC LIMIT 1").fetchone()
    accel = (latest and latest["mood"] is not None and latest["mood"] >= config.NIGHT_ACCEL_MOOD
             and latest["sleep_hours"] is not None and latest["sleep_hours"] < config.SHORT_SLEEP_HOURS)
    if accel:
        lines.append("")
        lines.append("（気づき：直近は気分が上がり気味で睡眠が短めです。今夜のアイデアは退避箱に"
                     "入れて、実行は明日の自分に渡すのが安全かもしれません。断定ではありません。）")

    return _ok("\n".join(lines), parked_today=parked,
               reserved_step=(reserved["step"] if reserved else None),
               bed_anchor=bed_anchor, night_accel=bool(accel))


# ---- 16. Re-entry: 止まった仕事へ責めずに戻る ----

def reenter_stalled(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    result = args.get("result")

    # 締めモード：再接続（完了ではない）を記録する
    if result is not None:
        if result not in ("sent", "partial", "not_yet"):
            return _ok("result は sent / partial / not_yet のどれかで記録してください。")
        reentry_id = args.get("reentry_id")
        if reentry_id:
            row = conn.execute("SELECT * FROM reentries WHERE id=?", (reentry_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM reentries WHERE reconnected_ts IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return _ok("記録中の再入場が見つかりませんでした。target を入れて新しく始めてください。")
        conn.execute("UPDATE reentries SET reconnected_ts=?, result=? WHERE id=?",
                     (_now_iso(), result, row["id"]))
        if result in ("sent", "partial"):
            conn.execute("INSERT INTO achievements (event_type, value, ts) VALUES ('reconnection', ?, ?)",
                         (row["target"], _now_iso()))
            return _ok(f"「{row['target']}」に再接続しました。完了かどうかは問いません。"
                       "止まっていた糸をもう一度つかんだ——それが今日の前進です。")
        return _ok(f"「{row['target']}」、今日はまだ送らない選択も記録しました。"
                   "戻ろうとした事実は消えません。次に開いたとき、ここから再開できます。")

    # 開始モード
    target = (args.get("target") or "").strip()
    if not target:
        reasons = "、".join(f"{k}（{v}）" for k, v in config.REENTRY_REASONS.items())
        return _ok("止まっているものを一言ください（例：〇〇さんへの返信、5月分の請求書）。"
                   f"理由も選べると入口が作りやすくなります：{reasons}")
    prefix = _safety_prefix(target)
    if prefix:
        return _ok(prefix)
    reason_key = args.get("reason")
    reason_label = config.REENTRY_REASONS.get(reason_key, reason_key)

    cur = conn.execute(
        "INSERT INTO reentries (target, reason, started_ts) VALUES (?,?,?)",
        (target, reason_label, _now_iso()),
    )

    lines = [f"「{target}」への再入場を始めます。"]
    if reason_label:
        lines.append(f"止まっていた理由：{reason_label}。能力の問題ではなく、よくある詰まり方です。")
    lines.append("")
    lines.append("再開文の型（3原則）：")
    lines.append("1. 謝りすぎない（お詫びは1文まで。長い謝罪は相手の負担になります）")
    lines.append("2. 言い訳・経緯説明をしない（相手が知りたいのは「これからどうなるか」）")
    lines.append("3. 次の一歩を1つだけ示す（「明日◯時までに△を送ります」の形）")
    lines.append("")
    lines.append("この型で短い再開文を下書きします。送るかどうかはあなたが決めてください。"
                 "送れたら result=sent、途中まで書けたら result=partial、"
                 "今日は無理そうなら result=not_yet で締められます（not_yet も立派な記録です）。")
    return _ok("\n".join(lines), reentry_id=cur.lastrowid, target=target)


# ---- 17. Low Battery: 谷の日の生活維持を最大3択に減らす ----

def low_battery_mode(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    d = args.get("date") or _today()
    existing = conn.execute("SELECT * FROM low_battery_logs WHERE date=?", (d,)).fetchone()

    def merged(name):
        if name in args:
            value = args.get(name)
            if name in ("water", "food", "meds_taken") and value is not None:
                return int(bool(value))
            return value
        return existing[name] if existing else None

    values = {name: merged(name) for name in
              ("water", "food", "meds_taken", "contacted", "dont_do", "note")}
    prefix = _safety_prefix(values["note"] or "")

    conn.execute(
        "INSERT INTO low_battery_logs "
        "(date, water, food, meds_taken, contacted, dont_do, note, updated_ts) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET water=excluded.water, food=excluded.food, "
        "meds_taken=excluded.meds_taken, contacted=excluded.contacted, "
        "dont_do=excluded.dont_do, note=excluded.note, updated_ts=excluded.updated_ts",
        (d, values["water"], values["food"], values["meds_taken"], values["contacted"],
         values["dont_do"], values["note"], _now_iso()),
    )

    choices = []
    if not values["water"]:
        choices.append("水分を手の届く場所に置く")
    if not values["food"]:
        choices.append("食べられそうなものを1つ確保する")
    if values["meds_taken"] is None:
        choices.append("服薬状況だけ確認する。迷うことは主治医・薬剤師へ")
    if not values["contacted"]:
        choices.append("必要なら、信頼できる人へ短い一言を作る")
    choices = choices[:3]

    lines = ["Low Battery モード。今日は生活維持だけで十分です。"]
    if values["dont_do"]:
        lines.append(f"今日やらないこと：「{values['dont_do']}」")
    if choices:
        lines.append("")
        lines.append("見える選択肢は最大3つだけ：")
        lines.extend(f"・{choice}" for choice in choices)
    else:
        lines.append("水分・食事・服薬状況など、今日の確認は置けています。ここから増やさなくて大丈夫です。")
    lines.append("")
    lines.append("これは診断や服薬指示ではありません。できない項目があっても評価しません。")
    text = "\n".join(lines)
    if prefix:
        text = prefix + "\n\n" + text
    return _ok(text, date=d, choices=choices, status=values)


# ---- 18. Money Fog: お金の不安を3つの実数へ分ける ----

def money_fog(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    d = args.get("date") or _today()
    existing = conn.execute("SELECT * FROM money_snapshots WHERE date=?", (d,)).fetchone()
    has_input = any(key in args for key in
                    ("stopped_payments", "debt_total", "income_expected", "next_item"))

    if not has_input and not existing:
        return _ok(
            "Money Fog は、お金の不安を判断せず3つの事実に分けます。\n\n"
            "1. 止まっている支払い\n2. 借金の残り（概算で可）\n3. 今月入る見込み\n\n"
            "分かる項目だけで大丈夫です。金融助言や評価はしません。"
        )

    def merged(name, default=None):
        if name in args:
            return args.get(name)
        return existing[name] if existing else default

    stopped = merged("stopped_payments", [])
    if isinstance(stopped, str):
        try:
            stopped = json.loads(stopped)
        except (TypeError, ValueError):
            stopped = [stopped]
    stopped = [str(item).strip() for item in (stopped or []) if str(item).strip()]
    debt_total = merged("debt_total")
    income_expected = merged("income_expected")
    for label, value in (("借金の残り", debt_total), ("今月入る見込み", income_expected)):
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            return _ok(f"{label}は数字で入力してください。概算で大丈夫です。", needs_input=True)
        if number < 0:
            return _ok(f"{label}は0以上の概算で入力してください。金融判断はせず、事実だけ置きます。",
                       needs_input=True)
        if label == "借金の残り":
            debt_total = number
        else:
            income_expected = number
    next_item = (merged("next_item") or "").strip() or (stopped[0] if stopped else "数字を1つ確認する")

    conn.execute(
        "INSERT INTO money_snapshots "
        "(date, stopped_payments, debt_total, income_expected, next_item, updated_ts) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET stopped_payments=excluded.stopped_payments, "
        "debt_total=excluded.debt_total, income_expected=excluded.income_expected, "
        "next_item=excluded.next_item, updated_ts=excluded.updated_ts",
        (d, json.dumps(stopped, ensure_ascii=False), debt_total, income_expected, next_item, _now_iso()),
    )

    def yen(value):
        return "未入力" if value is None else f"約 {float(value):,.0f} 円"

    lines = [
        "Money Fog。良し悪しを判断せず、いま見えている3つの事実だけ並べます。",
        "",
        f"1. 止まっている支払い：{('、'.join(stopped) if stopped else '未入力')}",
        f"2. 借金の残り：{yen(debt_total)}",
        f"3. 今月入る見込み：{yen(income_expected)}",
        "",
        f"今触る1項目だけ：{next_item}",
        "これは金融助言ではありません。正確でなくても、見える項目に分けた時点で十分です。",
    ]
    return _ok("\n".join(lines), date=d, stopped_payments=stopped,
               debt_total=debt_total, income_expected=income_expected, next_item=next_item)


# ---- 19. AI入口: 相談文から使う道具を安全優先で案内 ----

def choose_support_mode(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    text = (args.get("text") or "").strip()
    if not text:
        return _ok("いま困っていることを一言ください。診断ではなく、使えそうな道具を1つ案内します。")

    if safety.detect_crisis(text):
        return _ok(safety.crisis_message(), recommended_tool="route_to_crisis_support",
                   reason="危機サインを取りこぼさず、人につながることを最優先にするため")
    if safety.detect_med_discontinuation(text) or safety.detect_medical_advice_request(text):
        return _ok(safety.medical_advice_redirect(), recommended_tool=None,
                   reason="薬や診断の判断はCadenceでは扱わず、主治医へつなぐため")

    routes = (
        ("money_fog", ("お金", "支払い", "借金", "残高", "カード", "入金", "資金"),
         "お金の不安を3つの事実へ分ける"),
        ("start_wind_down", ("寝たい", "眠れない", "止まれない", "止まれな", "夜更かし", "深夜", "着地", "休みたい"),
         "今夜の続きが失われない状態を作って閉じる"),
        ("reenter_stalled", ("返信", "放置", "遅れ", "止まって", "再開", "請求", "公開できない"),
         "完了ではなく、止まったものへの再接続を作る"),
        ("low_battery_mode", ("動けない", "何もできない", "しんどい", "疲れ", "エネルギー", "谷"),
         "生活維持の選択肢を最大3つまでに減らす"),
        ("park_idea", ("アイデア", "思いつき", "忘れたくない", "作りたい", "ひらめき"),
         "思いつきを失わない退避箱へ置く"),
        ("break_down_task", ("大きすぎ", "わからない", "手をつけ", "先延ばし", "タスク"),
         "30秒で触れられる最初の一歩へ分ける"),
    )
    for tool_name, keywords, reason in routes:
        matched = [word for word in keywords if word in text]
        if matched:
            return _ok(
                f"使えそうな道具は `{tool_name}` です。理由：{reason}。\n"
                "これは診断や決めつけではありません。違うと感じたら使わなくて大丈夫です。",
                recommended_tool=tool_name, reason=reason, matched=matched,
            )
    return _ok(
        "まずは `log_daily_checkin` で、気分・睡眠・エネルギーのうち分かるものだけ置くのが良さそうです。"
        "これは診断ではなく、次の道具を選ぶための小さな現在地です。",
        recommended_tool="log_daily_checkin", reason="相談内容を評価せず、現在地を小さく外部化するため",
    )


# ---- 24. リマインド: 軽い声かけ（任意・最小限） ----

def list_due_reminders(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    """今の時刻と『いつもの起床・就寝アンカー』から、今あてはまる軽い声かけだけを返す。

    朝の30秒チェックイン・予約済みの最初の一歩・夜の着地を、根拠があるときだけ差し出す。
    早期警告は1件に集約。ストリーク・未達日数は数えない。すべて任意。
    （希死念慮など本物の危機はここでは扱わず、各記録ツールが検知時に安全ハブへ繋ぐ。）
    """
    from . import reminders

    now_arg = args.get("now")
    now_min = rhythm.to_minutes(now_arg) if now_arg else None
    if now_min is None:
        now_min = _now_min()

    today = _today()
    records = [dict(r) for r in conn.execute(
        "SELECT * FROM social_rhythm ORDER BY date").fetchall()]
    typical_wake = reminders.typical_anchor_min(records, "wake")
    typical_bed = reminders.typical_anchor_min(records, "bed")

    has_checkin = conn.execute(
        "SELECT 1 FROM checkins WHERE date=? LIMIT 1", (today,)).fetchone() is not None
    reserved_row = conn.execute(
        "SELECT step FROM first_steps WHERE date=? AND consumed=0", (today,)).fetchone()
    reserved_step = reserved_row["step"] if reserved_row else None
    day_closed = conn.execute(
        "SELECT 1 FROM day_closes WHERE date=? LIMIT 1", (today,)).fetchone() is not None

    checkins = [dict(r) for r in conn.execute(
        "SELECT * FROM checkins ORDER BY date, ts").fetchall()]
    signs = [dict(r) for r in conn.execute("SELECT * FROM warning_signs").fetchall()]
    for s in signs:
        try:
            s["actions"] = json.loads(s.get("actions") or "[]")
        except (ValueError, TypeError):
            s["actions"] = []
    early = signals.detect(checkins, signs)

    latest = conn.execute(
        "SELECT mood, sleep_hours FROM checkins ORDER BY date DESC, ts DESC LIMIT 1").fetchone()
    accel = bool(latest and latest["mood"] is not None and latest["mood"] >= config.NIGHT_ACCEL_MOOD
                 and latest["sleep_hours"] is not None and latest["sleep_hours"] < config.SHORT_SLEEP_HOURS)

    nudges = reminders.due_nudges(
        now_min=now_min,
        typical_wake_min=typical_wake,
        typical_bed_min=typical_bed,
        has_checkin_today=has_checkin,
        reserved_step=reserved_step,
        day_closed=day_closed,
        early_notices=early,
        acceleration=accel,
    )

    if not nudges:
        return _ok(
            "いまは特にお知らせはありません。必要になったら、こちらからそっと声をかけます。\n"
            + safety.DISCLAIMER,
            nudges=[], now=_min_to_hm(now_min),
            typical_wake=_min_to_hm(typical_wake), typical_bed=_min_to_hm(typical_bed),
        )

    lines = ["いま、そっとお伝えできることが少しあります（任意・無視してOK）：", ""]
    for n in nudges:
        lines.append(f"・{n['text']}")
    lines.append("")
    lines.append("これは最小限の声かけです。今のあなたに合わなければ、全部スルーして大丈夫。"
                 "ストリークも、できなかった日数も数えていません。")
    lines.append(safety.DISCLAIMER)
    return _ok("\n".join(lines), nudges=nudges, now=_min_to_hm(now_min),
               typical_wake=_min_to_hm(typical_wake), typical_bed=_min_to_hm(typical_bed))


# ====== 事業所向けモード（20〜23） ======

def _sanitize_filename(name: str) -> str:
    """英数・_.-・ひらがな/カタカナ/漢字のみ許可。それ以外は _ に置換。パストラバーサル防止。"""
    import re
    # 許可文字: ASCII英数・_.-・ひらがな(U+3040-309F)・カタカナ(U+30A0-30FF)・CJK統合漢字(U+4E00-9FFF)
    return re.sub(r"[^a-zA-Z0-9_.\-぀-ゟ゠-ヿ一-鿿]", "_", name)


# ---- 20. 事業所: 個別支援計画アセスメント登録 ----

def support_plan_intake(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    """個別支援計画のアセスメント情報を登録し、起草骨子とClaudeへの起草指示を返す。

    利用者テキスト（honnin_ikou/assessment）は第三者の言葉なので _safety_prefix() は通さない。
    """
    user_alias = (args.get("user_alias") or "").strip()
    if not user_alias:
        return _ok("利用者の呼び名（user_alias）を入れてください。イニシャル等で構いません。実名は入れないでください。")

    service_type = args.get("service_type")
    honnin_ikou = (args.get("honnin_ikou") or "").strip()
    assessment = (args.get("assessment") or "").strip()
    period_months = int(args.get("period_months") or 6)

    skeleton = {
        "1_本人・家族の意向": honnin_ikou or "（未記入）",
        "2_総合的な支援方針": "（Claudeが意向とアセスメントから起草）",
        "3_長期目標": f"（{period_months}ヶ月後の姿。本人の言葉に近い表現で）",
        "4_短期目標": "（3ヶ月単位・観察可能な行動レベルで2〜3個）",
        "5_支援内容": "（目標ごとに: 支援内容 / 担当 / 頻度 / 留意事項）",
        "6_本人の役割": "（できることベースで小さく）",
        "7_モニタリング時期": f"開始から3ヶ月後（中間）、{period_months}ヶ月後（更新）",
    }

    cur = conn.execute(
        "INSERT INTO support_plans "
        "(user_alias, service_type, honnin_ikou, assessment, period_months, skeleton, created_ts) "
        "VALUES (?,?,?,?,?,?,?)",
        (user_alias, service_type, honnin_ikou, assessment,
         period_months, json.dumps(skeleton, ensure_ascii=False), _now_iso()),
    )
    plan_id = cur.lastrowid

    text = (
        "【事業所向け・個別支援計画ドラフト】\n\n"
        f"アセスメント情報を登録しました（plan_id: {plan_id}）。\n\n"
        "このデータをもとに、以下の方針で計画案を起草してください：\n"
        "- 冒頭に「サービス管理責任者の確認・承認が必要なドラフトです」と明記する\n"
        "- 本人の意向の言葉を目標に必ず反映する（言い換えすぎない）\n"
        "- できないことの羅列ではなく、強み・できることを起点に書く\n"
        "- 「頑張る」「慣れる」などの抽象語は使わず、観察可能な行動レベルで書く\n"
        "  （例: ×「自信をつける」→ ○「週2回スタッフに声をかけて作業の確認ができる」）\n\n"
        "注意: user_alias にはイニシャル・呼び名のみを使用してください。実名や個人を特定できる情報を入れないでください。"
    )
    return _ok(text, plan_id=plan_id)


# ---- 21. 事業所: 個別支援計画一覧 ----

def support_plan_list(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    """登録済み個別支援計画の一覧と、モニタリング近接の案内を返す。"""
    rows = conn.execute(
        "SELECT id, user_alias, service_type, status, created_ts, period_months "
        "FROM support_plans ORDER BY id DESC"
    ).fetchall()
    plans = [dict(r) for r in rows]

    count = len(plans)
    if count == 0:
        return _ok("個別支援計画の登録はまだありません。support_plan_intake から登録できます。",
                   plans=[])

    text = f"登録済みの個別支援計画は {count} 件です。\n\n"
    text += "モニタリング時期の確認: 各プランの created_ts から period_months を加算した時期が、"
    text += "モニタリング・更新のタイミングになります。"
    text += "直近でモニタリングが必要なものをClaudeが一覧から確認して案内してください。"
    return _ok(text, plans=plans, count=count)


# ---- 22. 事業所: 個別支援計画 Word 出力 ----

def support_plan_export_docx(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    """個別支援計画ドラフトを .docx に書き出す。docx生成は docx_plan.build_support_plan_docx に委譲。"""
    plan_id = args.get("plan_id")
    if not plan_id:
        return _ok("plan_id を指定してください。")

    row = conn.execute("SELECT * FROM support_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        return _ok(f"plan_id {plan_id} の計画が見つかりません。support_plan_list で一覧を確認してください。")

    plan_dict = dict(row)

    # docx_plan は別エージェントが並列実装中。インターフェース契約に従って呼ぶ
    from . import docx_plan  # noqa: PLC0415

    draft_dict: Dict[str, Any] = {
        "policy": args.get("policy"),
        "long_goal": args.get("long_goal"),
        "short_goals": args.get("short_goals") or [],
        "honnin_role": args.get("honnin_role"),
        "monitoring": args.get("monitoring"),
        "period_from": args.get("period_from"),
        "period_to": args.get("period_to"),
        "created_date": _today_ja(),
    }

    docx_bytes: bytes = docx_plan.build_support_plan_docx(plan_dict, draft_dict)

    # 出力先は EXPORTS_DIR のみ（VAULT_ROOT には書かない）
    exports_dir = config.EXPORTS_DIR
    exports_dir.mkdir(parents=True, exist_ok=True)

    raw_name = f"support_plan_{plan_dict['user_alias']}_{plan_id}.docx"
    filename = _sanitize_filename(raw_name)
    filepath = exports_dir / filename

    filepath.write_bytes(docx_bytes)

    conn.execute(
        "UPDATE support_plans SET status='exported', exported_ts=?, export_file=? WHERE id=?",
        (_now_iso(), filename, plan_id),
    )

    text = (
        f"個別支援計画を出力しました。\n\n"
        f"保存先: {filepath}\n\n"
        "このファイルは「サービス管理責任者の確認・承認が必要なドラフト」です。"
        "そのまま利用者に渡さず、必ずサビ管が内容を確認・修正してから使用してください。"
    )
    return _ok(text, filepath=str(filepath), filename=filename, plan_id=plan_id)


# ---- 23. 事業所: 助成金・制度プレチェック ----

def subsidy_precheck(conn, args: Dict[str, Any]) -> Dict[str, Any]:
    """状況プロフィールから確認すべき公的制度カテゴリのチェックリストを返す。

    受給可否の判定はしない。最新要件はClaudeがweb検索で確認する前提。
    """
    profile = args.get("profile") or {}
    techo = profile.get("techo") or "なし"
    working = bool(profile.get("working"))
    tsuin = bool(profile.get("tsuin"))
    jichitai = (profile.get("jichitai") or "お住まいの市区町村").strip()

    checklist: List[str] = []

    if tsuin:
        checklist.append("自立支援医療（精神通院）— 医療費自己負担の軽減")
    if techo != "なし":
        checklist.append("障害者手帳に基づく税控除・公共料金等の減免")
        checklist.append("自治体独自の手当・助成（福祉手当等）")
    checklist.append("障害福祉サービス受給者証（就労系・生活系サービスの利用）")
    if not working:
        checklist.append("障害年金の受給可能性（初診日・納付要件の確認）")
    if working:
        checklist.append("障害者雇用枠・合理的配慮 / 就労定着支援")
    checklist.append("生活が苦しい場合: 生活福祉資金・住居確保給付金等の相談窓口")

    conn.execute(
        "INSERT INTO subsidy_checks (profile, checklist, created_ts) VALUES (?,?,?)",
        (json.dumps(profile, ensure_ascii=False),
         json.dumps(checklist, ensure_ascii=False),
         _now_iso()),
    )

    lines = [
        "【確認すべき制度カテゴリ】",
        "",
    ]
    for i, item in enumerate(checklist, 1):
        lines.append(f"{i}. {item}")

    lines += [
        "",
        f"一次窓口: {jichitai}の障害福祉課・基幹相談支援センター",
        "",
        "注意: このリストは「確認すべきカテゴリ」であり、受給可否の判定ではありません。",
        "各項目の最新の要件・金額・手続き方法は、Claudeがweb検索で当該自治体の公式情報を",
        "確認してから案内してください。年度や自治体によって大きく異なります。",
    ]

    text = "\n".join(lines)
    return _ok(text, checklist=checklist, jichitai=jichitai,
               primary_window=f"{jichitai}の障害福祉課・基幹相談支援センター")


# ====== レジストリ ======

HANDLERS = {
    "log_daily_checkin": log_daily_checkin,
    "log_social_rhythm": log_social_rhythm,
    "track_rhythm_regularity": track_rhythm_regularity,
    "build_action_plan": build_action_plan,
    "detect_early_warning": detect_early_warning,
    "break_down_task": break_down_task,
    "list_today_one_thing": list_today_one_thing,
    "create_if_then_plan": create_if_then_plan,
    "start_focus_timer": start_focus_timer,
    "track_achievement": track_achievement,
    "share_summary_with_supporter": share_summary_with_supporter,
    "route_to_crisis_support": route_to_crisis_support,
    "park_idea": park_idea,
    "reserve_first_step": reserve_first_step,
    "start_wind_down": start_wind_down,
    "reenter_stalled": reenter_stalled,
    "low_battery_mode": low_battery_mode,
    "money_fog": money_fog,
    "choose_support_mode": choose_support_mode,
    "list_due_reminders": list_due_reminders,
    # 事業所向けモード
    "support_plan_intake": support_plan_intake,
    "support_plan_list": support_plan_list,
    "support_plan_export_docx": support_plan_export_docx,
    "subsidy_precheck": subsidy_precheck,
}


def _str(desc: str, props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": required or []}}


TOOL_SPECS = {
    "log_daily_checkin": _str(
        "1日30秒・5項目以内の超軽量チェックイン。気分・睡眠・エネルギー・服薬・刺激物を記録し、メンタル日記に追記する。入れた項目だけでよい。",
        {
            "mood": {"type": "integer", "description": "気分 -5(とてもつらい)〜+5(とても上がっている)"},
            "sleep_hours": {"type": "number", "description": "睡眠時間（時間）"},
            "energy": {"type": "integer", "description": "エネルギー 0〜5"},
            "meds_taken": {"type": "boolean", "description": "服薬したか"},
            "stimulants": {"type": "string", "description": "飲酒・カフェイン等（任意）"},
            "note": {"type": "string", "description": "一言メモ（任意）"},
            "date": {"type": "string", "description": "YYYY-MM-DD（省略時は今日）"},
        }),
    "log_social_rhythm": _str(
        "社会リズムの『5つの定点』(起床・最初の対人接触・活動開始・夕食・就寝)の時刻を記録する（IPSRT/SRM）。",
        {
            "wake": {"type": "string", "description": "起床 HH:MM"},
            "first_contact": {"type": "string", "description": "最初に人と接した HH:MM"},
            "activity_start": {"type": "string", "description": "活動開始 HH:MM"},
            "dinner": {"type": "string", "description": "夕食 HH:MM"},
            "bed": {"type": "string", "description": "就寝 HH:MM"},
            "date": {"type": "string", "description": "YYYY-MM-DD（省略時は今日）"},
        }),
    "track_rhythm_regularity": _str(
        "直近の社会リズムから規則性スコア(0〜7)と、最もブレている定点を返す。診断ではなく気づきのため。",
        {"window_days": {"type": "integer", "description": "集計日数（既定7）"}}),
    "build_action_plan": _str(
        "双極性向け。本人の言葉の早期警告サイン(prodrome)と、その対処をアクションプランに登録する。汎用一覧は押し付けない。",
        {
            "signs": {"type": "array", "description": "サインの配列",
                      "items": {"type": "object", "properties": {
                          "type": {"type": "string", "enum": ["manic", "depressive"]},
                          "text": {"type": "string"},
                          "actions": {"type": "array", "items": {"type": "string"}}}}},
            "show_depressive_examples": {"type": "boolean", "description": "落ち込み側サインの例示を添える"},
        }),
    "detect_early_warning": _str(
        "双極性向け。チェックインと登録サインを突き合わせ、責めない『気づき』と本人の対処を提示する。断定・診断はしない。",
        {"lookback_days": {"type": "integer", "description": "さかのぼる日数（既定7）"}}),
    "break_down_task": _str(
        "ADHD向け。大きな/退屈なタスクを『今すぐ着手できる最初の一歩』に分ける。steps を渡せばそのまま保存する。",
        {
            "task": {"type": "string", "description": "分けたい大きなタスク"},
            "steps": {"type": "array", "items": {"type": "string"}, "description": "分解済みの小ステップ（先頭が最初の一歩）"},
            "blocked": {"type": "boolean", "description": "true なら一歩が大きすぎる＝さらに細かく"},
        }, ["task"]),
    "list_today_one_thing": _str(
        "ADHD向け。『今やる1個』だけを返す。ほかは隠す。complete_current で1個完了して次へ。",
        {
            "complete_current": {"type": "boolean", "description": "今の1個を完了にして次を出す"},
            "task_id": {"type": "integer", "description": "次に出したいタスクID（任意）"},
        }),
    "create_if_then_plan": _str(
        "『もし〈トリガー〉→〈行動〉』の実行意図を登録する。同時に持つのは1〜2個まで。",
        {
            "trigger": {"type": "string", "description": "いつ・どこで・何のあとに"},
            "action": {"type": "string", "description": "そのとき取る具体行動"},
            "cue_type": {"type": "string", "enum": ["time", "location", "preceding_action"]},
            "cue_value": {"type": "string"},
        }, ["trigger", "action"]),
    "start_focus_timer": _str(
        "ADHD向け。可変ポモドーロのタイムボックスを開始する。result_note を渡すと終了として記録する。",
        {
            "duration_min": {"type": "integer", "description": "長さ（分・既定25）"},
            "task_id": {"type": "integer"},
            "estimate_min": {"type": "integer", "description": "所要の見積り（任意）"},
            "body_double_mode": {"type": "string", "enum": ["off", "ai", "recorded", "peer"]},
            "result_note": {"type": "string", "description": "終了時：何ができたかを一言（これがあると締める）"},
            "session_id": {"type": "integer", "description": "締めたいセッションID（任意）"},
        }),
    "track_achievement": _str(
        "『前に進んだ』記録を可視化する。採点・他者比較・ランキングはしない。過去の自分比のみ。",
        {
            "event_type": {"type": "string", "description": "task_done / habit / exercise / checkin など（任意）"},
            "value": {"type": "string"},
        }),
    "share_summary_with_supporter": _str(
        "本人が consent を立てたときだけ、直近の要約を支援者/主治医へ共有する“プレビュー”を作る。自動送信はしない。",
        {
            "consent": {"type": "boolean", "description": "明示的な共有同意（必須）"},
            "recipient": {"type": "string", "description": "宛先（事前に決めた支援者/主治医）"},
            "days": {"type": "integer", "description": "対象日数（既定7）"},
            "format": {"type": "string", "enum": ["message", "csv"]},
        }),
    "route_to_crisis_support": _str(
        "全ツールの安全ハブ。希死念慮・深刻な落ち込みのとき、24時間の専門窓口へ橋渡しする。",
        {}),
    "park_idea": _str(
        "Landing（夜の着地）。寝る前に浮かぶ思いつき・アイデアを退避箱へ入れる。今やらない・消えない・"
        "明日拾える、の3点を保証する。アイデア日記のINBOXにも追記される。",
        {
            "text": {"type": "string", "description": "思いつきの内容（断片で良い）"},
            "context": {"type": "string", "description": "補足・関連プロジェクト名など（任意）"},
        }, ["text"]),
    "reserve_first_step": _str(
        "Landing（夜の着地）。明日の最初の一歩を1つだけ予約する。常に1つで、入れ直すと置き換わる。"
        "翌朝 list_today_one_thing が最優先で差し出す。30秒で着手できる小ささを推奨。",
        {
            "step": {"type": "string", "description": "明日の最初の一歩（小さく）"},
            "date": {"type": "string", "description": "実行日 YYYY-MM-DD（省略時は明日）"},
        }, ["step"]),
    "start_wind_down": _str(
        "Landing（夜の着地）。夜の加速を静かに着地させる手順。引数なしで現状確認"
        "（退避箱・明日の一歩・開きっぱなしのタイマー・就寝アンカー）と3手順を返す。"
        "close を立てると『今日はここまで』を記録して閉じる。作業を禁止せず、失わない状態を作って手放す。",
        {
            "close": {"type": "boolean", "description": "true で今日を閉じる"},
            "note": {"type": "string", "description": "閉じるときの一言（任意）"},
        }),
    "reenter_stalled": _str(
        "Re-entry（再入場）。止まってしまった返信・請求・公開などへ責めずに戻る。target と理由を渡すと"
        "再開文の型（謝りすぎない・経緯説明しない・次の一歩を1つ）を返すので、Claude が短い再開文を下書きする。"
        "result（sent/partial/not_yet）を渡すと『再接続』として記録する。完了ではなく再接続を祝う。",
        {
            "target": {"type": "string", "description": "止まっている事柄（例：〇〇さんへの返信）"},
            "reason": {"type": "string",
                       "description": "止まっていた理由。fear/perfectionism/forgot/energy/unclear/other か自由記述"},
            "result": {"type": "string", "enum": ["sent", "partial", "not_yet"],
                       "description": "締めるとき：送れた/途中まで/今日はまだ"},
            "reentry_id": {"type": "integer", "description": "締めたい再入場のID（省略時は直近）"},
        }),
    "low_battery_mode": _str(
        "Low Battery（谷の日）。生活維持の選択肢を最大3つまでに減らす。水分・食事・服薬状況・"
        "連絡・今日やらないことを記録するが、診断や服薬指示、達成評価はしない。",
        {
            "water": {"type": "boolean", "description": "水分を置けた/取れたか（任意）"},
            "food": {"type": "boolean", "description": "食べられるものを確保したか（任意）"},
            "meds_taken": {"type": "boolean", "description": "服薬状況の記録。判断や指示には使わない"},
            "contacted": {"type": "string", "description": "連絡した人・連絡先（任意）"},
            "dont_do": {"type": "string", "description": "今日やらないと決めること（任意）"},
            "note": {"type": "string", "description": "一言メモ。危機語があれば安全ハブを表示"},
            "date": {"type": "string", "description": "YYYY-MM-DD（省略時は今日）"},
        }),
    "money_fog": _str(
        "Money Fog。お金の不安を、止まっている支払い・借金残・今月入る見込みの3事実へ分け、"
        "今触る1項目だけを表示する。金融助言・評価・借入提案はしない。",
        {
            "stopped_payments": {"type": "array", "items": {"type": "string"},
                                 "description": "止まっている支払いの名前（分かる分だけ）"},
            "debt_total": {"type": "number", "description": "借金残の概算（円・任意）"},
            "income_expected": {"type": "number", "description": "今月入る見込みの概算（円・任意）"},
            "next_item": {"type": "string", "description": "今触る1項目（任意）"},
            "date": {"type": "string", "description": "YYYY-MM-DD（省略時は今日）"},
        }),
    "choose_support_mode": _str(
        "AI向けの安全な入口。相談文から、Cadenceのどの道具が合いそうかを1つ案内する。"
        "診断や自動実行はせず、危機サインは route_to_crisis_support を最優先にする。",
        {
            "text": {"type": "string", "description": "いま困っていること・相談文"},
        }, ["text"]),
    "list_due_reminders": _str(
        "軽い声かけ（リマインド）。今の時刻と『いつもの起床・就寝アンカー』をもとに、"
        "朝の30秒チェックイン・予約済みの最初の一歩・夜の着地(start_wind_down)を“今あてはまる分だけ”差し出す。"
        "早期警告の気づきは1件に集約。ストリークや未達日数は数えず、すべて任意。"
        "希死念慮など本物の危機はここでは扱わず route_to_crisis_support を最優先にする。"
        "セッション開始時や『何かある？』に応えるとき、定時のチェックに使う。",
        {
            "now": {"type": "string", "description": "現在時刻 HH:MM（省略時は実時刻。テスト・任意）"},
        }),
    # --- 事業所向けモード ---
    "support_plan_intake": _str(
        "【事業所向け】個別支援計画のアセスメント情報を登録し、起草骨子とClaudeへの起草指示を返す。"
        "最終判断は必ずサービス管理責任者が行う前提。",
        {
            "user_alias": {"type": "string",
                           "description": "利用者の呼び名（イニシャル等。実名・個人特定情報は入れない）"},
            "service_type": {"type": "string",
                             "enum": list(config.SERVICE_TYPES),
                             "description": "サービス種別"},
            "honnin_ikou": {"type": "string",
                            "description": "本人・家族の意向（聞き取った言葉のまま）"},
            "assessment": {"type": "string",
                           "description": "アセスメント要点（強み・課題・生活状況・配慮事項）"},
            "period_months": {"type": "integer",
                              "description": "計画期間（月数・既定6）"},
        }, ["user_alias"]),
    "support_plan_list": _str(
        "【事業所向け】登録済み個別支援計画ドラフトの一覧を返す。"
        "モニタリング時期の確認にも使う。",
        {}),
    "support_plan_export_docx": _str(
        "【事業所向け】起草済みの個別支援計画ドラフトをWord(.docx)に出力する。"
        "出力先は ~/.cadence/exports/ のみ。サビ管の確認用ドラフトである旨を必ず案内する。",
        {
            "plan_id": {"type": "integer", "description": "support_plan_intake で発行されたID"},
            "policy": {"type": "string", "description": "総合的な支援方針（起草済み文章）"},
            "long_goal": {"type": "string", "description": "長期目標"},
            "short_goals": {
                "type": "array",
                "description": "短期目標2〜3個",
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "短期目標（観察可能な行動レベル）"},
                        "support": {"type": "string", "description": "支援内容"},
                        "staff": {"type": "string", "description": "担当"},
                        "frequency": {"type": "string", "description": "頻度（例: 週2回）"},
                        "note": {"type": "string", "description": "留意事項（任意）"},
                    },
                },
            },
            "honnin_role": {"type": "string", "description": "本人の役割"},
            "monitoring": {"type": "string", "description": "モニタリング時期（任意）"},
            "period_from": {"type": "string", "description": "計画開始日（任意）"},
            "period_to": {"type": "string", "description": "計画終了日（任意）"},
        }, ["plan_id"]),
    "subsidy_precheck": _str(
        "【本人・家族向け】状況を登録し、確認すべき公的制度カテゴリのチェックリストを返す。"
        "受給可否の判定はしない。最新の要件・金額はClaudeがweb検索で当該自治体の公式情報を確認する前提。",
        {
            "profile": {
                "type": "object",
                "description": "利用者のプロフィール",
                "properties": {
                    "techo": {"type": "string",
                              "enum": list(config.TECHO_TYPES),
                              "description": "障害者手帳の種別"},
                    "working": {"type": "boolean", "description": "就労中か"},
                    "tsuin": {"type": "boolean", "description": "精神科等に通院中か"},
                    "jichitai": {"type": "string", "description": "お住まいの自治体（市区町村名）"},
                },
            },
        }, ["profile"]),
}


def dispatch(name: str, args: Dict[str, Any], conn) -> Dict[str, Any]:
    handler = HANDLERS.get(name)
    if not handler:
        return {"text": f"未知のツールです: {name}", "_error": True}
    try:
        return handler(conn, args or {})
    except Exception as exc:  # noqa: BLE001 — ツール内エラーは利用者に優しく返す
        return {"text": f"うまく実行できませんでした（{type(exc).__name__}: {exc}）。"
                        "もう一度お願いします。", "_error": True}
