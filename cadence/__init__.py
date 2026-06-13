"""Cadence — 躁鬱・ADHD のための、Claude と連携する生活リズム＆気分モニタリング。

これは医療機器でも診断ツールでもありません。気づきと習慣づくりの「補助」です
（一次治療・人的支援の代わりにはなりません）。つらいときの専門窓口へは、いつでも
route_to_crisis_support から繋がります。

設計の背骨:
    記録(log_*) → 気づき(track_*/detect_*) → 行動の足場(break_down/if_then/focus)
    → 共有(share) → 安全ハブ(route_to_crisis_support)

すべて標準ライブラリのみ（Python 3.9+）。データはローカル(~/.cadence)と Vault の
メンタル日記に置き、第三者に送りません。
"""

__version__ = "0.2.0"
