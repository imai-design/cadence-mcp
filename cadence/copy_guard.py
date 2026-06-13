"""出力コピーの安全lint — 診断断定・罰・恥・煽り・他者比較を出力に混ぜない番人。

safety_guardrails を機械的に守るために、Cadence が利用者へ返す文言はここを通す。
テストでも、ツール出力にこれらの表現が紛れ込んでいないか検査する。
"""
import re
from typing import List

# 診断・断定・医療グレードを装う表現（FDA の general wellness ラインを越えない）
_BANNED_DIAGNOSTIC = [
    r"あなたは(今)?(躁|うつ|双極|病気|発症)",
    r"診断します", r"と診断", r"臨床的に", r"医療グレード",
    r"治します", r"治せます", r"治療できます",
]
# 罰・恥・自己批判を煽る表現
_BANNED_SHAMING = [
    r"サボ(っ|り|る)", r"怠け", r"ダメな(あなた|人)", r"失敗です", r"だらしな",
    r"意志が弱", r"記録が途切れました", r"連続が途切れ", r"また.{0,4}できなかった",
]
# 他者比較・順位づけ
_BANNED_COMPARISON = [
    r"ランキング", r"順位", r"他の人より", r"平均より(下|低|劣)", r"リーダーボード",
]

_CATEGORIES = (
    ("diagnostic", _BANNED_DIAGNOSTIC),
    ("shaming", _BANNED_SHAMING),
    ("comparison", _BANNED_COMPARISON),
)


def check_copy(text: str) -> List[str]:
    """禁止表現の違反リストを返す（空なら安全）。"""
    if not text:
        return []
    violations = []
    for category, patterns in _CATEGORIES:
        for pattern in patterns:
            if re.search(pattern, text):
                violations.append(f"{category}: /{pattern}/ に一致")
    return violations


def is_safe_copy(text: str) -> bool:
    return not check_copy(text)
