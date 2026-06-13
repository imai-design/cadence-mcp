"""早期警告サインの検知（断定でなく「気づき」を返す純関数）。

チェックイン履歴と、本人が登録したサインを突き合わせ、責めない短い気づきと、
（登録があれば）本人自身の言葉の対処手順を返す。診断や「あなたは躁です」のような
断定は決してしない。深刻な内容は呼び出し側で安全ハブ（route_to_crisis_support）へ。

注: うつ側のサインは躁ほど精度よく検知できない。長い睡眠などは目安に留め、過信させない。
"""
from typing import Callable, Dict, List, Optional

from . import config


def _lt(value, threshold) -> bool:
    return value is not None and value < threshold


def _gt(value, threshold) -> bool:
    return value is not None and value > threshold


def _trailing_streak(items: List[Dict], pred: Callable[[Dict], bool]) -> int:
    """末尾（最新）から連続して条件を満たす日数。"""
    count = 0
    for item in reversed(items):
        if pred(item):
            count += 1
        else:
            break
    return count


def _actions_for(signs: List[Dict], sign_type: str) -> List[str]:
    out: List[str] = []
    for s in signs:
        if s.get("sign_type") == sign_type:
            acts = s.get("actions") or []
            if isinstance(acts, str):
                acts = [acts]
            out.extend(acts)
    return out


def detect(
    checkins: List[Dict],
    signs: Optional[List[Dict]] = None,
    lookback_days: Optional[int] = None,
) -> List[Dict]:
    """気づきのリストを返す。各要素 {kind, level, message, actions}。

    level は 'info' か 'attention' のみ（断定・診断はしない）。
    checkins は古い順のチェックイン dict のリスト。
    """
    signs = signs or []
    days = lookback_days or config.EARLY_WARNING_LOOKBACK_DAYS
    recent = checkins[-days:] if days else checkins
    notices: List[Dict] = []

    # 1) 短い睡眠の連続（短い睡眠は躁転の引き金になりやすい）
    short_streak = _trailing_streak(recent, lambda c: _lt(c.get("sleep_hours"), config.SHORT_SLEEP_HOURS))
    if short_streak >= config.SHORT_SLEEP_STREAK:
        notices.append({
            "kind": "short_sleep",
            "level": "attention",
            "message": (
                f"ここ{short_streak}日、睡眠が短めの日が続いています。"
                "睡眠が削れる時期は、無理がきいて見えても後で反動が来やすいタイミングです。"
                "今夜はいつもの時間に休めそうですか。"
            ),
            "actions": _actions_for(signs, "manic"),
        })

    # 2) 長い睡眠の連続（落ち込み側の目安。躁ほど確かではないので info に留める）
    long_streak = _trailing_streak(recent, lambda c: _gt(c.get("sleep_hours"), config.LONG_SLEEP_HOURS))
    if long_streak >= config.LONG_SLEEP_STREAK:
        notices.append({
            "kind": "long_sleep",
            "level": "info",
            "message": (
                f"ここ{long_streak}日、睡眠が長めの日が続いています。"
                "体が休息を必要としているのかもしれません。無理に良し悪しを判断しなくて大丈夫です。"
            ),
            "actions": _actions_for(signs, "depressive"),
        })

    # 3) 気分の振れ幅
    moods = [c.get("mood") for c in recent if c.get("mood") is not None]
    if len(moods) >= 2 and (max(moods) - min(moods)) >= config.MOOD_SWING_DELTA:
        notices.append({
            "kind": "mood_swing",
            "level": "info",
            "message": (
                "ここ数日で気分の振れ幅が大きめです。良い悪いではなく、"
                "波があること自体は自然なこと。気づいておくだけで十分です。"
            ),
            "actions": [],
        })

    return notices
