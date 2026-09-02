#!/usr/bin/env python3
"""從 YAML 風格的表單定義產生 Word (.docx) 檔案。

不需要任何第三方套件 —— .docx 就是一個 ZIP，裡面放 Office Open XML。
本腳本只用 Python 標準函式庫的 zipfile 與字串組裝。

用法：
    python3 _工具/產生表單.py                # 產生 _表單範本/ 底下所有表單
    python3 _工具/產生表單.py --list         # 只列出會產生哪些檔
    python3 _工具/產生表單.py 機房巡檢表     # 只產生指定的表單

表單定義寫在 _工具/表單定義.py 的 FORMS 裡。
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

VAULT = Path(__file__).resolve().parent.parent
OUT_DIR = VAULT / "_表單範本"

# ── OOXML 樣板 ────────────────────────────────────────────────
CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# 中文字型設定：eastAsia 指定中文字型，ascii/hAnsi 指定西文字型
FONT = ('<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" '
        'w:eastAsia="Microsoft JhengHei" w:cs="Calibri"/>')

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>{FONT}<w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
  <w:name w:val="Normal"/><w:rPr>{FONT}<w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title">
  <w:name w:val="Title"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr>
  <w:rPr>{FONT}<w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1">
  <w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
  <w:rPr>{FONT}<w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid">
  <w:name w:val="Table Grid"/>
  <w:tblPr><w:tblBorders>
    <w:top w:val="single" w:sz="6" w:color="666666"/>
    <w:left w:val="single" w:sz="6" w:color="666666"/>
    <w:bottom w:val="single" w:sz="6" w:color="666666"/>
    <w:right w:val="single" w:sz="6" w:color="666666"/>
    <w:insideH w:val="single" w:sz="6" w:color="666666"/>
    <w:insideV w:val="single" w:sz="6" w:color="666666"/>
  </w:tblBorders></w:tblPr></w:style>
</w:styles>"""


def _run(text: str, bold: bool = False, size: int | None = None) -> str:
    rpr = FONT + ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/>' if size else "")
    return f"<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r>"


def para(text: str = "", style: str | None = None, bold: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_run(text, bold)}</w:p>"


def title(text: str) -> str:
    return para(text, style="Title")


def heading(text: str) -> str:
    return para(text, style="Heading1")


def _cell(text: str, width: int, bold: bool, shaded: bool) -> str:
    shd = '<w:shd w:val="clear" w:fill="E8E8E8"/>' if shaded else ""
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shd}'
            f'<w:vAlign w:val="center"/></w:tcPr>{para_in_cell(text, bold)}</w:tc>')


def para_in_cell(text: str, bold: bool) -> str:
    return f'<w:p><w:pPr><w:spacing w:before="40" w:after="40"/></w:pPr>{_run(text, bold)}</w:p>'


def table(headers: list[str], rows: list[list[str]], widths: list[int] | None = None) -> str:
    n = len(headers)
    widths = widths or [int(9360 / n)] * n
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    out = [f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
           f'<w:tblW w:w="9360" w:type="dxa"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    out.append("<w:tr><w:trPr><w:tblHeader/></w:trPr>" +
               "".join(_cell(h, w, True, True) for h, w in zip(headers, widths)) + "</w:tr>")
    for r in rows:
        cells = list(r) + [""] * (n - len(r))
        out.append("<w:tr>" + "".join(_cell(c, w, False, False)
                                      for c, w in zip(cells, widths)) + "</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def build_docx(path: Path, body_parts: list[str]) -> None:
    body = "".join(body_parts)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:body>{body}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
                '</w:sectPr></w:body></w:document>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/document.xml", document)


def render(form: dict) -> list[str]:
    """把表單定義轉成 OOXML 片段清單。"""
    parts = [title(form["title"])]
    if form.get("desc"):
        parts.append(para(form["desc"]))
    for block in form["blocks"]:
        kind = block["type"]
        if kind == "heading":
            parts.append(heading(block["text"]))
        elif kind == "para":
            parts.append(para(block["text"]))
        elif kind == "table":
            parts.append(table(block["headers"], block.get("rows", []), block.get("widths")))
            parts.append(para())
        elif kind == "fields":
            rows = [[label, ""] for label in block["labels"]]
            parts.append(table(["項目", "填寫欄"], rows, [2600, 6760]))
            parts.append(para())
        else:
            raise SystemExit(f"未知的區塊型別：{kind}")
    if form.get("source"):
        parts.append(para())
        parts.append(para(f"— 本表單出自《資訊設備安裝、部署、設定、優化、維護教學手冊》"
                          f"　對應章節：{form['source']}"))
    return parts


def main() -> None:
    sys.path.insert(0, str(VAULT / "_工具"))
    try:
        from 表單定義 import FORMS  # noqa: N811
    except ImportError:
        raise SystemExit("找不到 _工具/表單定義.py")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--list" in sys.argv:
        for f in FORMS:
            print(f"{f['file']:<40} {f['title']}  （來源：{f.get('source', '—')}）")
        print(f"\n共 {len(FORMS)} 份表單")
        return

    targets = [f for f in FORMS if not args or f["title"] in args or f["file"] in args]
    if not targets:
        raise SystemExit(f"找不到符合的表單：{args}")

    for f in targets:
        out = OUT_DIR / f["file"]
        build_docx(out, render(f))
        print(f"已產生：{out.relative_to(VAULT)}  ({out.stat().st_size:,} bytes)")
    print(f"\n共 {len(targets)} 份，輸出於 {OUT_DIR.relative_to(VAULT)}/")


if __name__ == "__main__":
    main()
