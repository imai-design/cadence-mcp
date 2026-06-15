"""安全ガード — 危機・減薬意図・医療判断要求の検知と、専門窓口への橋渡し。

ここでの「検知」は診断ではない。つらいサインを取りこぼさず専門窓口へ繋ぐための、
控えめな安全網。判定に迷ったら必ず安全側（窓口を出す）に倒す。
"""
import re
from typing import List

from . import config

DISCLAIMER = (
    "※これは医療機器でも診断でもありません。気づきと習慣の補助です。"
    "治療や薬のことは主治医に相談してください。"
)

# 希死念慮・自傷の語（取りこぼしを防ぐため広めに。迷えば窓口を出す）。
# 否定形・略語・助詞抜きの言い回しまで安全側に広く拾う。
_CRISIS_PATTERNS = [
    r"死にたい", r"死のう", r"死んだほうが", r"死ぬ(しか|以外)",
    r"消え(て)?(なくなりたい|たい)", r"消えてしまいたい",
    r"(居|い)なくなりたい", r"自殺", r"自死",
    r"生き(ていたく|たく)ない",
    r"首(を)?(吊|つ)", r"飛び降り", r"飛び込(み|ん)",
    r"リストカット", r"リスカ", r"自傷",
    r"(?<![A-Za-z])OD(?![A-Za-z])", r"オーバードーズ", r"過量服薬", r"過剰摂取",
    r"生きてても(意味|しょうがない|仕方)",
    r"(生きる|生きてる|存在).{0,3}(意味|価値).{0,3}(ない|無い|わからない)",
    r"楽になりたい", r"終わりにしたい", r"いっそ.*(死|消)", r"殺して",
]

# 自己判断の減薬・断薬の意図
_MED_STOP_PATTERNS = [
    r"薬.{0,6}(やめ|止め|やめる|断つ|飲まない|飲むのをやめ)",
    r"断薬", r"自分で.{0,4}(減ら|やめ)", r"薬.{0,4}減ら",
    r"(飲むの|服薬).{0,4}(やめ|止め)",
]

# 医学的判断を求める要求（用量・相互作用・診断）
_MED_ADVICE_PATTERNS = [
    r"何\s*mg", r"\d+\s*mg", r"用量", r"増やしても(いい|平気|大丈夫)",
    r"飲み合わせ", r"併用して(いい|大丈夫)", r"副作用.{0,6}(大丈夫|平気|問題ない)",
    r"診断して", r"これは(躁|うつ|双極|病気)ですか",
]


def _matches(text: str, patterns: List[str]) -> bool:
    if not text:
        return False
    return any(re.search(p, text) for p in patterns)


def detect_crisis(text: str) -> bool:
    """希死念慮・自傷をうかがわせる表現があれば True。"""
    return _matches(text, _CRISIS_PATTERNS)


def detect_med_discontinuation(text: str) -> bool:
    """自己判断で薬をやめる/減らす意図があれば True。"""
    return _matches(text, _MED_STOP_PATTERNS)


def detect_medical_advice_request(text: str) -> bool:
    """用量・相互作用・診断など医学的判断を求めていれば True。"""
    return _matches(text, _MED_ADVICE_PATTERNS)


def crisis_message() -> str:
    """専門窓口を 2〜3 件、希望のメッセージとともに返す（安全ハブの中核）。"""
    lines = [
        "いま、とてもつらいのかもしれません。あなたは一人で抱えなくていいです。",
        "下の窓口は、いますぐ・無料で・あなたの味方として話を聞いてくれます。",
        "",
    ]
    for c in config.CRISIS_CONTACTS_JP:
        lines.append(f"・{c['name']}：{c['contact']}（{c['hours']}）— {c['note']}")
    e = config.EMERGENCY_JP
    lines.append(f"・{e['name']}：{e['contact']}（{e['note']}）")
    lines.append("")
    lines.append(
        "私はAIで、専門家の代わりにはなれません。"
        "でも、あなたが誰かに繋がるまで、ここで一緒にいます。"
    )
    return "\n".join(lines)


def med_nudge_message() -> str:
    """減薬・断薬の意図を検知したときの、止めない・指示しないナッジ。"""
    return (
        "お薬を自分の判断で急にやめると、再発のリスクが上がることが知られています。"
        "減らしたい・やめたいと感じたら、まず主治医に相談して、相談しながら少しずつ"
        "（漸減）進めるのが安全です。Cadence は服薬の量ややめ方を指示・判断しません。"
    )


def medical_advice_redirect() -> str:
    """用量・相互作用・診断などを求められたときの差し戻し。"""
    return (
        "用量・飲み合わせ・副作用・診断といった医学的な判断は、主治医または薬剤師に"
        "相談する事柄です。Cadence はそこには立ち入りません"
        "（飲んだ／飲んでいないの単純な記録やリマインドはできます）。"
    )
