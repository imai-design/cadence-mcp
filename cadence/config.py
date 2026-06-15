"""Cadence の設定値を一箇所に集約する（パス・専門窓口・検知しきい値）。

窓口の連絡先やしきい値の点検・更新を一箇所で行えるように、定数はここに集める。
"""
import os
from pathlib import Path

# === 保存先 ===
# データ本体（SQLite）はホーム直下の隠しフォルダに置く。
CADENCE_HOME = Path.home() / ".cadence"
DB_PATH = CADENCE_HOME / "cadence.db"

# === Vault ミラー（任意機能）===
# 気分ログや退避アイデアの「人が読める正本」を、Obsidian 等の Vault に追記する。
# 個人ごとに場所が違うため、ハードコードせず次の順で解決する。未設定なら無効
# （公開配布時の既定。ローカルのみのプライベートな運用になる）。
#   1) 環境変数 CADENCE_VAULT_ROOT
#   2) ~/.cadence/.vault_path（git 管理外のローカル設定。1 行にパスを書く）
#   3) どちらも無ければ None（Vault への書き込みをしない）
def _resolve_vault_root():
    env = os.environ.get("CADENCE_VAULT_ROOT")
    if env:
        return Path(env)
    local = CADENCE_HOME / ".vault_path"
    try:
        if local.exists():
            value = local.read_text(encoding="utf-8").strip()
            if value:
                return Path(value)
    except OSError:
        pass
    return None


VAULT_ROOT = _resolve_vault_root()
MENTAL_DIARY_DIR = (VAULT_ROOT / "メンタル日記") if VAULT_ROOT else None
IDEA_INBOX_DIR = (VAULT_ROOT / "アイデア日記" / "INBOX") if VAULT_ROOT else None

# === 専門窓口（route_to_crisis_support の正本。定期点検する） ===
# 番号は実在のもの。出典は厚生労働省の電話相談案内など。
CRISIS_CONTACTS_JP = (
    {
        "name": "よりそいホットライン",
        "contact": "0120-279-338",
        "hours": "24時間・通話無料",
        "note": "どんな悩みでも。ガイダンス後に専門の相談につながる",
    },
    {
        "name": "#いのちSOS",
        "contact": "0120-061-338",
        "hours": "24時間・通話無料",
        "note": "つらい気持ち・消えたい気持ちの相談",
    },
    {
        "name": "自殺予防いのちの電話",
        "contact": "0120-783-556",
        "hours": "毎日16:00〜21:00・通話無料",
        "note": "毎月10日は8:00〜翌朝8:00。一人で抱えないで",
    },
)
EMERGENCY_JP = {
    "name": "緊急（いま命の危険があるとき）",
    "contact": "119",
    "note": "ためらわず呼んでいい",
}

# === セルフモニタリングの上限（強迫化を防ぐ） ===
MAX_CHECKIN_ITEMS = 5            # 1回の記録は5項目まで
CHECKIN_TIME_BUDGET_SEC = 30     # 1日30秒で終わる粒度を目安に

# === 気分・エネルギーのスケール ===
MOOD_MIN, MOOD_MAX = -5, 5       # 気分: -5(とてもつらい) 〜 +5(とても上がっている)
ENERGY_MIN, ENERGY_MAX = 0, 5

# === 社会リズム（IPSRT / SRM-II-5 準拠） ===
# 5つの定点（アンカー）の時刻を毎日一定に保てているかを 0〜7 点で測る。
RHYTHM_ANCHORS = ("wake", "first_contact", "activity_start", "dinner", "bed")
RHYTHM_ANCHOR_LABELS = {
    "wake": "起床",
    "first_contact": "最初に人と接した",
    "activity_start": "活動・仕事の開始",
    "dinner": "夕食",
    "bed": "就寝",
}
SRM_TOLERANCE_MIN = 45           # いつもの時刻の ±45分以内なら「規則的」とみなす
RHYTHM_DEFAULT_WINDOW_DAYS = 7

# === 早期警告サインのしきい値（断定でなく「気づき」のため） ===
SHORT_SLEEP_HOURS = 5.0          # これ未満を「短い睡眠」とみなす
SHORT_SLEEP_STREAK = 2           # 連続で続いたら気づきを出す（短い睡眠は躁転の引き金になりやすい）
LONG_SLEEP_HOURS = 10.0          # これ超を「長い睡眠」（落ち込み側の目安）
LONG_SLEEP_STREAK = 3
MOOD_SWING_DELTA = 4             # 直近数日の気分変動幅がこれ以上で「揺れ」に気づく
EARLY_WARNING_LOOKBACK_DAYS = 7

# === リマインド（軽い声かけ）===
# 通知は最小限・任意・責めない。ストリークや未達日数は数えない。
# 朝は起床アンカーから一定時間以内に、夜は就寝アンカーの一定時間手前にだけ差し出す。
REMINDER_MORNING_WINDOW_MIN = 180   # 起床からこの分数以内なら「朝の声かけ」を出してよい
REMINDER_EVENING_WINDOW_MIN = 90    # 就寝のこの分数手前から「夜の着地」を出してよい
REMINDER_TYPICAL_WINDOW_DAYS = 14   # 「いつもの時刻」を求めるためにさかのぼる日数

# === if-then プラン（実行意図）===
MAX_ACTIVE_IF_THEN = 2           # 同時に持つのは1〜2個まで（絞るほど効く）

# === フォーカスタイマー ===
DEFAULT_FOCUS_MIN = 25

# === Landing（夜の着地） ===
DEFAULT_BED_ANCHOR = "00:00"        # 就寝記録がまだ無いときの仮アンカー
NIGHT_ACCEL_MOOD = 2                # 直近の気分がこれ以上 かつ 短い睡眠 → 夜の加速に気づきを出す
WIND_DOWN_STEPS = (
    "頭に残っている思いつきを park_idea に全部出す（失わない箱に入る）",
    "明日の最初の一歩を reserve_first_step で1つだけ予約する",
    "画面を閉じる。続きは明日のあなたが拾える状態になっている",
)

# === Re-entry（止まった仕事への再入場） ===
REENTRY_REASONS = {
    "fear": "返事や反応がこわかった",
    "perfectionism": "完璧にしてから出そうとしていた",
    "forgot": "忘れていた・流れてしまった",
    "energy": "エネルギーが足りなかった",
    "unclear": "次に何をするかが曖昧だった",
    "other": "その他",
}

# === 事業所向けモード（障害福祉×AI） ===
EXPORTS_DIR = CADENCE_HOME / "exports"

SERVICE_TYPES = (
    "就労移行",
    "就労継続A",
    "就労継続B",
    "生活介護",
    "自立訓練",
    "児童発達支援",
    "放課後等デイ",
    "その他",
)

TECHO_TYPES = (
    "精神",
    "療育",
    "身体",
    "なし",
    "申請中",
)
