"""社会リズム（IPSRT / SRM-II-5）の規則性を、記録から計算する純関数群。

各定点（起床・最初の対人接触・活動開始・夕食・就寝）が「いつもの時刻の ±45分以内」
に行えているかを数え、0〜7点の規則性スコアと、最もブレている定点を返す。
治療判断はしない。あくまで「何時が一番ブレているか」の気づきのため。
"""
from statistics import median
from typing import Dict, List, Optional

from . import config


def to_minutes(hhmm: Optional[str]) -> Optional[int]:
    """'HH:MM' を 0〜1439 分に変換。不正値は None。"""
    if not hhmm:
        return None
    try:
        h, m = str(hhmm).split(":")
        minutes = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None
    if 0 <= minutes < 1440:
        return minutes
    return None


def _circular_diff(a: int, b: int) -> int:
    """24時間円環上での差（分）。就寝が日付をまたぐ場合に対応。"""
    diff = abs(a - b) % 1440
    return min(diff, 1440 - diff)


def regularity(
    records: List[Dict],
    window_days: Optional[int] = None,
    tol_min: Optional[int] = None,
) -> Dict:
    """直近 window 日の社会リズム記録から規則性を集計する。

    records: [{date, wake, first_contact, activity_start, dinner, bed}, ...]（古い順）
    戻り値: {score_0_7, per_anchor, shakiest, days_counted}
    """
    tol = tol_min if tol_min is not None else config.SRM_TOLERANCE_MIN
    window = window_days or config.RHYTHM_DEFAULT_WINDOW_DAYS
    recent = records[-window:] if window else records

    per_anchor: Dict[str, Dict] = {}
    regs: List[float] = []

    for anchor in config.RHYTHM_ANCHORS:
        mins = [to_minutes(r.get(anchor)) for r in recent]
        mins = [m for m in mins if m is not None]
        label = config.RHYTHM_ANCHOR_LABELS[anchor]

        if len(mins) < 2:
            per_anchor[anchor] = {
                "label": label, "regularity": None, "spread_min": None, "days": len(mins),
            }
            continue

        base = int(median(mins))
        hits = sum(1 for m in mins if _circular_diff(m, base) <= tol)
        reg = hits / len(mins)
        spread = max(_circular_diff(m, base) for m in mins)
        per_anchor[anchor] = {
            "label": label, "regularity": round(reg, 2),
            "spread_min": spread, "days": len(mins),
        }
        regs.append(reg)

    score = round((sum(regs) / len(regs)) * 7, 1) if regs else None

    rated = [(a, d) for a, d in per_anchor.items() if d["regularity"] is not None]
    shakiest = None
    if rated:
        # 規則性が最も低い定点（同点なら、ばらつき幅が大きいほう）
        shakiest = min(rated, key=lambda kv: (kv[1]["regularity"], -kv[1]["spread_min"]))[0]

    return {
        "score_0_7": score,
        "per_anchor": per_anchor,
        "shakiest": shakiest,
        "days_counted": len(recent),
    }
