"""軽い声かけ（リマインド）の算出 — いつ・何を差し出すかを決める純関数群。

設計の約束:
- 通知は最小限・任意・責めない。ストリークや「サボった日数」は数えない。
- 朝は起床アンカーから一定時間以内に、夜は就寝アンカーの手前にだけ差し出す。
- 早期警告の気づきは1件に集約して出す（連投・畳みかけをしない）。
- 希死念慮など本物の危機は、ここでは扱わない。バッチ化・保留は決してせず、
  検知した瞬間に安全ハブ（route_to_crisis_support）へ最優先で繋ぐ（呼び出し側の責務）。

時刻に依存しないよう、現在時刻は分（0〜1439）で受け取る純関数にしてある（テスト容易性）。
"""
from statistics import median
from typing import Dict, List, Optional

from . import config
from .rhythm import to_minutes


def typical_anchor_min(records: List[Dict], anchor: str,
                       window_days: Optional[int] = None) -> Optional[int]:
    """直近の社会リズム記録から、アンカーの『いつもの時刻』(分)を中央値で返す。

    records: [{date, wake, ..., bed}, ...]（古い順）。
    2日分以上の有効な記録が必要。足りなければ None（＝声かけの根拠が無いので出さない）。
    """
    window = window_days or config.REMINDER_TYPICAL_WINDOW_DAYS
    recent = records[-window:] if window else records
    mins = [to_minutes(r.get(anchor)) for r in recent]
    mins = [m for m in mins if m is not None]
    if len(mins) < 2:
        return None
    return int(median(mins))


def _forward(a: int, b: int) -> int:
    """24時間円環で、時刻 a から時刻 b へ進む分数（0〜1439）。就寝が日付をまたぐ場合に対応。"""
    return (b - a) % 1440


def due_nudges(
    *,
    now_min: int,
    typical_wake_min: Optional[int] = None,
    typical_bed_min: Optional[int] = None,
    has_checkin_today: bool = False,
    reserved_step: Optional[str] = None,
    day_closed: bool = False,
    early_notices: Optional[List[Dict]] = None,
    acceleration: bool = False,
    morning_window_min: Optional[int] = None,
    evening_window_min: Optional[int] = None,
) -> List[Dict]:
    """いま差し出してよい『軽い声かけ』のリストを返す。

    各要素: {kind, level, text, suggested_tool}
    level は 'info' か 'attention' のみ（断定・診断はしない）。
    該当が無ければ空リスト（＝何も言わない。沈黙も尊重する）。
    """
    morning_w = morning_window_min if morning_window_min is not None else config.REMINDER_MORNING_WINDOW_MIN
    evening_w = evening_window_min if evening_window_min is not None else config.REMINDER_EVENING_WINDOW_MIN
    early_notices = early_notices or []
    nudges: List[Dict] = []

    in_morning = (typical_wake_min is not None
                  and _forward(typical_wake_min, now_min) <= morning_w)
    approaching_bed = (typical_bed_min is not None
                       and _forward(now_min, typical_bed_min) <= evening_w)

    # 朝: 30秒チェックイン（まだ今日の記録が無いときだけ）
    if in_morning and not has_checkin_today:
        nudges.append({
            "kind": "morning_checkin",
            "level": "info",
            "text": ("おはようございます。よかったら今日の30秒チェックイン"
                     "（気分・睡眠・エネルギーのうち分かるものだけ）を置いていけます。"
                     "置かない選択も大丈夫です。"),
            "suggested_tool": "log_daily_checkin",
        })

    # 朝〜日中: 昨夜予約した最初の一歩（あれば。就寝間際には急かさない）
    if reserved_step and not approaching_bed:
        nudges.append({
            "kind": "reserved_step",
            "level": "info",
            "text": (f"昨夜のあなたが、今日の最初の一歩を1つだけ予約しています：「{reserved_step}」。"
                     "気が向いたときに、これだけで大丈夫です。"),
            "suggested_tool": "list_today_one_thing",
        })

    # 夜: 就寝アンカーの手前で、静かな着地をそっと（もう閉じていれば出さない）
    if approaching_bed and not day_closed:
        text = ("そろそろ着地の時間かもしれません。今日を閉じるなら、思いつきを失わない形にして"
                "手放す手順（start_wind_down）が使えます。まだ続けたいなら、それでも大丈夫です。")
        if acceleration:
            text += ("\n（最近は睡眠が短めで気分が上がり気味のようです。今夜の思いつきは退避箱へ入れて、"
                     "実行は明日の自分に渡すのが安全かもしれません。断定ではありません。）")
        nudges.append({
            "kind": "evening_winddown",
            "level": "attention" if acceleration else "info",
            "text": text,
            "suggested_tool": "start_wind_down",
        })

    # 早期警告は『集約して1件』だけ（連投しない）。本物の危機はここでは扱わない。
    if early_notices:
        attention = [n for n in early_notices if n.get("level") == "attention"]
        lead = (attention or early_notices)[0]
        more = len(early_notices) - 1
        text = "そっとお伝えします（断定ではなく気づきです）：" + lead.get("message", "")
        if more > 0:
            text += f"\nほかにも {more} 件、小さな気づきがあります（detect_early_warning で見られます）。"
        nudges.append({
            "kind": "early_warning",
            "level": lead.get("level", "info"),
            "text": text,
            "suggested_tool": "detect_early_warning",
        })

    return nudges
