"""Vault のメンタル日記へ、気分チェックインの「人が読める正本」を追記する。

本人が手で書いた内容は決して消さない（読み込んで末尾に足すだけ）。ファイルが
無ければ、メンタル日記のテンプレートで新規作成する。すべてローカル・第三者送信なし。
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config

_CADENCE_HEADER = "## Cadence ログ"


def diary_path(date: str) -> Path:
    return config.MENTAL_DIARY_DIR / f"{date}.md"


def _new_file_body(date: str) -> str:
    return (
        f"---\ndate: {date}\ntags: [メンタル日記]\n---\n\n"
        f"# {date}\n\n{_CADENCE_HEADER}\n"
    )


def append_checkin(date: str, summary_line: str, now: Optional[str] = None) -> Optional[str]:
    """その日のメンタル日記に、チェックイン1行を時系列で追記し、パスを返す。

    Vault が未設定（MENTAL_DIARY_DIR is None）なら何もせず None を返す。
    """
    if config.MENTAL_DIARY_DIR is None:
        return None
    path = diary_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = now or datetime.now().strftime("%H:%M")
    entry = f"- {stamp} {summary_line}"

    if path.exists():
        text = path.read_text(encoding="utf-8").rstrip()
        if _CADENCE_HEADER not in text:
            text += f"\n\n{_CADENCE_HEADER}"
        text += f"\n{entry}\n"
        path.write_text(text, encoding="utf-8")
    else:
        path.write_text(_new_file_body(date) + entry + "\n", encoding="utf-8")
    return str(path)


def inbox_path(date: str) -> Path:
    return config.IDEA_INBOX_DIR / f"{date} 退避箱.md"


def append_parked_idea(date: str, idea_line: str, now: Optional[str] = None) -> Optional[str]:
    """アイデア日記/INBOX のその日の退避箱ファイルに1行追記し、パスを返す。

    退避箱の約束は「失わない」。既存の内容は消さず、末尾に足すだけ。
    Vault が未設定（IDEA_INBOX_DIR is None）なら何もせず None を返す（記録は DB 側に残る）。
    """
    if config.IDEA_INBOX_DIR is None:
        return None
    path = inbox_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = now or datetime.now().strftime("%H:%M")
    entry = f"- {stamp} {idea_line}"

    if path.exists():
        text = path.read_text(encoding="utf-8").rstrip()
        path.write_text(text + f"\n{entry}\n", encoding="utf-8")
    else:
        body = (
            f"---\ndate: {date}\ntags: [アイデア, 退避箱, Cadence]\n---\n\n"
            f"# {date} 退避箱\n\n"
            "夜に浮かんだ思いつきの避難先。今やらない・消えない・明日の自分が拾える。\n\n"
        )
        path.write_text(body + entry + "\n", encoding="utf-8")
    return str(path)
