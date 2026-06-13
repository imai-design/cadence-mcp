"""
docx_plan.py — 個別支援計画書の .docx 生成モジュール
標準ライブラリ（zipfile, io, html, datetime）のみ使用（外部パッケージ禁止）。
Python 3.9 互換。
生成される .docx はサービス管理責任者の確認・承認前のドラフトである。

公開関数:
    build_support_plan_docx(plan: dict, draft: dict) -> bytes
"""

import io
import zipfile
import html
from datetime import date
from typing import Optional

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
# A4縦: 11906 x 16838 DXA / 余白 上下1100・左右1440
CONTENT_W = 9026       # = 11906 - 1440 * 2
LABEL_W   = 2300
VALUE_W   = CONTENT_W - LABEL_W  # 6726

JP_FONT       = "Yu Gothic"
COLOR_BORDER  = "444444"
COLOR_LABEL   = "EFEFEF"    # ラベル列・署名ヘッダ網掛け
COLOR_GOAL_H  = "DCE6F1"    # 短期目標表ヘッダ
COLOR_DRAFT   = "AA0000"    # 赤字注記

# 短期目標表 列幅 (合計 = 9026)
GOAL_COLS = [2200, 2800, 1500, 1300, 1226]
# 署名欄 列幅 (合計 = 9026)
SIGN_COLS = [3009, 3009, 3008]


# ---------------------------------------------------------------------------
# XML ユーティリティ
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """XML エスケープ（& < > " を処理）。"""
    return html.escape(str(text) if text is not None else "", quote=True)


def _font_run(text: str, *, bold: bool = False, size: int = 21,
              color: Optional[str] = None) -> str:
    """w:r 要素（テキストランを返す）。"""
    props = [f'<w:rFonts w:ascii="{JP_FONT}" w:eastAsia="{JP_FONT}"/>']
    if bold:
        props.append("<w:b/>")
    props.append(f"<w:sz w:val=\"{size}\"/>")
    props.append(f"<w:szCs w:val=\"{size}\"/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    rpr = "<w:rPr>" + "".join(props) + "</w:rPr>"
    return f"<w:r>{rpr}<w:t xml:space=\"preserve\">{_esc(text)}</w:t></w:r>"


def _para(runs: str, *, align: str = "", space_before: int = 0,
          space_after: int = 60) -> str:
    """w:p 要素。runs は w:r の文字列連結。"""
    jc = f'<w:jc w:val="{align}"/>' if align else ""
    spacing = f'<w:spacing w:before="{space_before}" w:after="{space_after}"/>'
    ppr = f"<w:pPr>{jc}{spacing}</w:pPr>"
    return f"<w:p>{ppr}{runs}</w:p>"


def _border_xml() -> str:
    """共通の単線罫線セット（上下左右）。"""
    b = f'style="single" w:sz="4" w:space="0" w:color="{COLOR_BORDER}"'
    sides = "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{COLOR_BORDER}"/>'
        for side in ("top", "left", "bottom", "right")
    )
    return f"<w:tcBorders>{sides}</w:tcBorders>"


def _tbl_borders_xml() -> str:
    sides = "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{COLOR_BORDER}"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    return f"<w:tblBorders>{sides}</w:tblBorders>"


def _shd_xml(fill: str) -> str:
    return f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'


def _cell_margins_xml(top: int = 100, bottom: int = 100,
                      left: int = 140, right: int = 140) -> str:
    return (f'<w:tcMar>'
            f'<w:top w:w="{top}" w:type="dxa"/>'
            f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
            f'<w:left w:w="{left}" w:type="dxa"/>'
            f'<w:right w:w="{right}" w:type="dxa"/>'
            f'</w:tcMar>')


# ---------------------------------------------------------------------------
# 段落ヘルパ
# ---------------------------------------------------------------------------

def _title_paragraph() -> str:
    """タイトル「個 別 支 援 計 画 書」中央・太字・size30。"""
    run = _font_run("個 別 支 援 計 画 書", bold=True, size=30)
    return _para(run, align="center", space_before=120, space_after=200)


def _draft_notice_paragraph() -> str:
    """赤字注記（中央・size18・AA0000）。"""
    text = ("【ドラフト】本書はAI支援により作成された案であり、"
            "サービス管理責任者の確認・承認をもって正式版となります。")
    run = _font_run(text, size=18, color=COLOR_DRAFT)
    return _para(run, align="center", space_before=0, space_after=200)


def _section_heading(text: str) -> str:
    """小見出し段落（太字・size24・上余白240）。"""
    run = _font_run(text, bold=True, size=24)
    return _para(run, space_before=240, space_after=120)


def _spacer_paragraph(space_before: int = 160) -> str:
    return _para("", space_before=space_before, space_after=0)


# ---------------------------------------------------------------------------
# セルヘルパ
# ---------------------------------------------------------------------------

def _multiline_cell_content(text: str) -> str:
    """改行を複数の w:p に分割して返す（セル内用）。"""
    lines = str(text or "").split("\n")
    result = []
    for i, line in enumerate(lines):
        after = 40 if i < len(lines) - 1 else 0
        run = _font_run(line)
        result.append(_para(run, space_after=after))
    return "".join(result) if result else _para("")


def _label_cell(text: str, width: int) -> str:
    """ラベル列セル（薄グレー網掛け・太字・縦中央）。"""
    content = _para(_font_run(text, bold=True), space_after=0)
    tcpr = (f"<w:tcPr>"
            f'<w:tcW w:w="{width}" w:type="dxa"/>'
            f"{_border_xml()}"
            f"{_shd_xml(COLOR_LABEL)}"
            f"<w:vAlign w:val=\"center\"/>"
            f"{_cell_margins_xml()}"
            f"</w:tcPr>")
    return f"<w:tc>{tcpr}{content}</w:tc>"


def _value_cell(text: str, width: int) -> str:
    """値列セル（通常）。"""
    content = _multiline_cell_content(text)
    tcpr = (f"<w:tcPr>"
            f'<w:tcW w:w="{width}" w:type="dxa"/>'
            f"{_border_xml()}"
            f"{_cell_margins_xml()}"
            f"</w:tcPr>")
    return f"<w:tc>{tcpr}{content}</w:tc>"


def _header_cell(text: str, width: int, fill: str = COLOR_GOAL_H) -> str:
    """ヘッダセル（網掛け・太字・中央揃え）。"""
    run = _font_run(text, bold=True)
    content = _para(run, align="center", space_after=0)
    tcpr = (f"<w:tcPr>"
            f'<w:tcW w:w="{width}" w:type="dxa"/>'
            f"{_border_xml()}"
            f"{_shd_xml(fill)}"
            f"<w:vAlign w:val=\"center\"/>"
            f"{_cell_margins_xml()}"
            f"</w:tcPr>")
    return f"<w:tc>{tcpr}{content}</w:tc>"


def _sign_empty_cell(width: int) -> str:
    """署名欄の空セル（高さ確保のため上余白500）。"""
    content = _para(_font_run("　"), space_after=0)
    tcpr = (f"<w:tcPr>"
            f'<w:tcW w:w="{width}" w:type="dxa"/>'
            f"{_border_xml()}"
            f"{_cell_margins_xml(top=500)}"
            f"</w:tcPr>")
    return f"<w:tc>{tcpr}{content}</w:tc>"


# ---------------------------------------------------------------------------
# 行・表ヘルパ
# ---------------------------------------------------------------------------

def _label_value_row(label: str, value: str) -> str:
    """ラベル/値 2列の行。"""
    label_cell = _label_cell(label, LABEL_W)
    value_cell = _value_cell(value, VALUE_W)
    return f"<w:tr>{label_cell}{value_cell}</w:tr>"


def _tbl_props_xml(col_widths: "list[int]") -> str:
    """w:tblPr + w:tblGrid を組み立てる。"""
    total_w = sum(col_widths)
    tbl_pr = (f"<w:tblPr>"
              f'<w:tblW w:w="{total_w}" w:type="dxa"/>'
              f"{_tbl_borders_xml()}"
              f"<w:tblLayout w:type=\"fixed\"/>"
              f"</w:tblPr>")
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in col_widths)
    tbl_grid = f"<w:tblGrid>{grid}</w:tblGrid>"
    return tbl_pr + tbl_grid


def _wrap_table(rows: str, col_widths: "list[int]") -> str:
    """rows（行 XML 文字列）を table タグで包む。"""
    return f"<w:tbl>{_tbl_props_xml(col_widths)}{rows}</w:tbl>"


# ---------------------------------------------------------------------------
# 各ブロック生成
# ---------------------------------------------------------------------------

def _build_info_table(plan: dict, draft: dict) -> str:
    """利用者情報テーブル（ラベル/値 7行）。"""
    today = date.today()
    created = draft.get("created_date") or f"{today.year}/{today.month}/{today.day}"

    pf = draft.get("period_from") or "　　年　　月　　日"
    pt = draft.get("period_to")   or "　　年　　月　　日"
    pm = plan.get("period_months", "")
    period_str = f"{pf} ～ {pt}（{pm}ヶ月）"

    rows = "".join([
        _label_value_row("利用者氏名", f"{plan.get('user_alias', '')}　様"),
        _label_value_row("サービス種別", plan.get("service_type", "")),
        _label_value_row("計画作成日", created),
        _label_value_row("計画期間", period_str),
        _label_value_row("本人・家族の意向", plan.get("honnin_ikou", "")),
        _label_value_row("総合的な支援方針", draft.get("policy", "")),
        _label_value_row("長期目標", draft.get("long_goal", "")),
    ])
    return _wrap_table(rows, [LABEL_W, VALUE_W])


def _build_short_goals_table(draft: dict) -> str:
    """短期目標と支援内容テーブル（5列）。"""
    headers = ["短期目標", "支援内容", "担当", "頻度", "留意事項"]
    header_cells = "".join(
        _header_cell(h, GOAL_COLS[i]) for i, h in enumerate(headers)
    )
    header_row = f"<w:tr>{header_cells}</w:tr>"

    goal_rows = []
    for g in (draft.get("short_goals") or []):
        vals = [
            g.get("goal", ""),
            g.get("support", ""),
            g.get("staff", ""),
            g.get("frequency", ""),
            g.get("note", ""),
        ]
        cells = "".join(_value_cell(v, GOAL_COLS[i]) for i, v in enumerate(vals))
        goal_rows.append(f"<w:tr>{cells}</w:tr>")

    rows = header_row + "".join(goal_rows)
    return _wrap_table(rows, GOAL_COLS)


def _build_misc_table(draft: dict) -> str:
    """本人の役割 / モニタリング時期テーブル。"""
    rows = "".join([
        _label_value_row("本人の役割", draft.get("honnin_role", "")),
        _label_value_row("モニタリング時期", draft.get("monitoring", "")),
    ])
    return _wrap_table(rows, [LABEL_W, VALUE_W])


def _build_sign_table() -> str:
    """署名欄テーブル（3列: ヘッダ行 + 空白行）。"""
    labels = ["サービス管理責任者", "作成担当者", "本人（同意）署名"]
    header_cells = "".join(
        _header_cell(h, SIGN_COLS[i], fill=COLOR_LABEL) for i, h in enumerate(labels)
    )
    header_row = f"<w:tr>{header_cells}</w:tr>"

    empty_cells = "".join(_sign_empty_cell(SIGN_COLS[i]) for i in range(3))
    empty_row = f"<w:tr>{empty_cells}</w:tr>"

    return _wrap_table(header_row + empty_row, SIGN_COLS)


# ---------------------------------------------------------------------------
# document.xml 本体
# ---------------------------------------------------------------------------

def _build_document_xml(plan: dict, draft: dict) -> str:
    """document.xml 全体を組み立てる。"""
    body_parts = [
        _title_paragraph(),
        _draft_notice_paragraph(),
        _build_info_table(plan, draft),
        _section_heading("短期目標と支援内容"),
        _build_short_goals_table(draft),
        _spacer_paragraph(160),
        _build_misc_table(draft),
        _spacer_paragraph(300),
        _build_sign_table(),
        # セクション末尾の sectPr
        _section_pr_xml(),
    ]
    body = "<w:body>" + "".join(body_parts) + "</w:body>"

    ns = (
        'xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:cx="http://schemas.microsoft.com/office/drawing/2014/chartex" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:aink="http://schemas.microsoft.com/office/drawing/2016/ink" '
        'xmlns:am3d="http://schemas.microsoft.com/office/drawing/2017/model3d" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:oel="http://schemas.microsoft.com/office/2019/extlst" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" '
        'xmlns:w16cex="http://schemas.microsoft.com/office/word/2018/wordml/cex" '
        'xmlns:w16cid="http://schemas.microsoft.com/office/word/2016/wordml/cid" '
        'xmlns:w16="http://schemas.microsoft.com/office/word/2018/wordml" '
        'xmlns:w16sdtdh="http://schemas.microsoft.com/office/word/2020/wordml/sdtdatahash" '
        'xmlns:w16se="http://schemas.microsoft.com/office/word/2015/wordml/symex" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 w15 w16se w16cid w16 w16cex w16sdtdh wp14"'
    )
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}>{body}</w:document>'


def _section_pr_xml() -> str:
    """セクションプロパティ（A4縦・余白設定）。"""
    return (
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1100" w:right="1440" w:bottom="1100" w:left="1440" '
        'w:header="709" w:footer="709" w:gutter="0"/>'
        "</w:sectPr>"
    )


# ---------------------------------------------------------------------------
# OOXML パーツ（最小構成）
# ---------------------------------------------------------------------------

_CONTENT_TYPES_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>"""

_WORD_RELS_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>"""


# ---------------------------------------------------------------------------
# 公開関数
# ---------------------------------------------------------------------------

def build_support_plan_docx(plan: dict, draft: dict) -> bytes:
    """個別支援計画書の .docx を bytes で返す（A4縦）。

    plan:  {user_alias, service_type, honnin_ikou, period_months}
    draft: {policy, long_goal, short_goals: [{goal, support, staff, frequency, note?}],
            honnin_role, monitoring?, period_from?, period_to?, created_date?}
    欠けたキーは .get で安全に既定値処理する。
    """
    doc_xml = _build_document_xml(plan, draft)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # [Content_Types].xml を先頭に
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML.encode("utf-8"))
        zf.writestr("_rels/.rels", _RELS_XML.encode("utf-8"))
        zf.writestr("word/_rels/document.xml.rels", _WORD_RELS_XML.encode("utf-8"))
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))

    return buf.getvalue()


# ---------------------------------------------------------------------------
# 自己検証
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    PLAN = {
        "user_alias": "山田　太郎",
        "service_type": "就労継続支援B型",
        "honnin_ikou": "自分のペースで働きたい。仲間と一緒に作業するのが楽しい。",
        "period_months": 6,
    }
    DRAFT = {
        "policy": "本人の意向を尊重しながら、安心して通所できる環境を整え、生活リズムの安定を目指す。",
        "long_goal": "週3日以上の安定した通所を継続し、自信を持って作業に取り組めるようになる。",
        "short_goals": [
            {
                "goal": "週2日、定時に来所できる",
                "support": "前日にリマインド連絡を行い、送迎支援を実施する",
                "staff": "生活支援員",
                "frequency": "週2回",
                "note": "体調不良時は早退可。無理のない範囲で継続を促す。",
            },
            {
                "goal": "作業手順を一人で確認できる",
                "support": "手順書を見やすい場所に掲示し、困ったときは声かけする",
                "staff": "職業指導員",
                "frequency": "毎日",
                "note": "",
            },
        ],
        "honnin_role": "毎朝体調を自己チェックし、気になることはスタッフに伝える。",
        "monitoring": "3ヶ月後（2026年9月）",
        "period_from": "2026年4月1日",
        "period_to": "2026年9月30日",
        "created_date": "2026/4/1",
    }

    out_path = "/tmp/docx_selftest.docx"
    data = build_support_plan_docx(PLAN, DRAFT)
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"[OK] {out_path} ({len(data)} bytes) を生成しました")

    # --- zip 健全性確認 ---
    import xml.dom.minidom as minidom

    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()
        bad = zf.testzip()
        print(f"[zip] namelist: {names}")
        print(f"[zip] testzip:  {bad!r}  (None = 全エントリ正常)")

    # --- XML well-formed 確認 ---
    with zipfile.ZipFile(out_path) as zf:
        minidom.parseString(zf.read("word/document.xml"))
    print("[xml] document.xml: well-formed OK")

    # --- textutil 検証は呼び出し側から実行してください ---
    print("[done] 自己検証完了。次コマンドでテキスト変換を確認:")
    print(f"  textutil -convert txt -output /tmp/docx_selftest.txt {out_path}")
