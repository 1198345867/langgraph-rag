from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor, Twips

DOC_SKILL_SCRIPTS = Path(
    r"C:\Users\ASUS\.codex\plugins\cache\openai-primary-runtime\documents"
    r"\26.813.12317\skills\documents\scripts"
)
sys.path.insert(0, str(DOC_SKILL_SCRIPTS))

from table_geometry import apply_table_geometry, column_widths_from_weights  # noqa: E402


OUTPUT_PATH = Path(
    r"C:\Users\ASUS\Desktop\langgraph RAG"
    r"\LangGraph_RAG私有文档问答系统技术总结.docx"
)

CONTENT_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120
TABLE_MARGINS = {"top": 80, "bottom": 80, "start": 120, "end": 120}

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
INK_BLUE = "0B2545"
BODY = "24364B"
MUTED = "5E6B7A"
GRID = "C8D2DE"
HEADER_FILL = "E8EEF5"
SOFT_FILL = "F4F6F9"
LIGHT_FILL = "F2F4F7"
CAUTION_FILL = "FFF6E5"
PAGE_WIDTH = 9360

CN_FONT = "微软雅黑"
LATIN_FONT = "Calibri"
MONO_FONT = "Consolas"


def set_run_font(
    run,
    *,
    name: str = LATIN_FONT,
    east_asia: str = CN_FONT,
    size: float | None = None,
    color: str | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
) -> None:
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), east_asia)
    if size is not None:
        run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def set_style_font(
    style,
    *,
    name: str = LATIN_FONT,
    east_asia: str = CN_FONT,
    size: float | None = None,
    color: str | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
) -> None:
    style.font.name = name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), east_asia)
    if size is not None:
        style.font.size = Pt(size)
    if color:
        style.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        style.font.bold = bold
    if italic is not None:
        style.font.italic = italic


def set_style_spacing(
    style,
    *,
    before: float | None = None,
    after: float | None = None,
    line: float | None = None,
) -> None:
    fmt = style.paragraph_format
    if before is not None:
        fmt.space_before = Pt(before)
    if after is not None:
        fmt.space_after = Pt(after)
    if line is not None:
        fmt.line_spacing = line


def set_keep_with_next(paragraph, value: bool = True) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    keep = p_pr.find(qn("w:keepNext"))
    if value and keep is None:
        p_pr.append(OxmlElement("w:keepNext"))
    elif not value and keep is not None:
        p_pr.remove(keep)


def shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)
    shd.set(qn("w:val"), "clear")


def set_table_borders(table, color: str = GRID, size: int = 4) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), str(size))
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def add_field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, text, end])


def add_numbering_definition(numbering, *, num_id: int, abstract_id: int, bullet: bool) -> None:
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "hybridMultilevel")
    abstract.append(multi)

    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    num_fmt = OxmlElement("w:numFmt")
    num_fmt.set(qn("w:val"), "bullet" if bullet else "decimal")
    lvl_text = OxmlElement("w:lvlText")
    lvl_text.set(qn("w:val"), "•" if bullet else "%1.")
    lvl_jc = OxmlElement("w:lvlJc")
    lvl_jc.set(qn("w:val"), "left")
    level.extend([start, num_fmt, lvl_text, lvl_jc])

    p_pr = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "num")
    tab.set(qn("w:pos"), "540")
    tabs.append(tab)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "540")
    ind.set(qn("w:hanging"), "270")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:after"), "80")
    spacing.set(qn("w:line"), "300")
    spacing.set(qn("w:lineRule"), "auto")
    p_pr.extend([tabs, ind, spacing])
    level.append(p_pr)

    r_pr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    rfonts.set(qn("w:ascii"), LATIN_FONT)
    rfonts.set(qn("w:hAnsi"), LATIN_FONT)
    rfonts.set(qn("w:eastAsia"), CN_FONT)
    r_pr.append(rfonts)
    level.append(r_pr)
    abstract.append(level)

    numbering.append(abstract)
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_num_id = OxmlElement("w:abstractNumId")
    abstract_num_id.set(qn("w:val"), str(abstract_id))
    num.append(abstract_num_id)
    numbering.append(num)


def configure_numbering(doc: Document) -> None:
    numbering = doc.part.numbering_part.element
    existing_num_ids = {
        int(item.get(qn("w:numId")))
        for item in numbering.findall(qn("w:num"))
        if item.get(qn("w:numId"))
    }
    existing_abstract_ids = {
        int(item.get(qn("w:abstractNumId")))
        for item in numbering.findall(qn("w:abstractNum"))
        if item.get(qn("w:abstractNumId"))
    }
    bullet_num = max(existing_num_ids, default=0) + 1
    decimal_num = bullet_num + 1
    bullet_abstract = max(existing_abstract_ids, default=-1) + 1
    decimal_abstract = bullet_abstract + 1
    add_numbering_definition(
        numbering,
        num_id=bullet_num,
        abstract_id=bullet_abstract,
        bullet=True,
    )
    add_numbering_definition(
        numbering,
        num_id=decimal_num,
        abstract_id=decimal_abstract,
        bullet=False,
    )

    for style_name, num_id in (("RAG Bullet", bullet_num), ("RAG Number", decimal_num)):
        style = doc.styles[style_name]
        p_pr = style.element.get_or_add_pPr()
        num_pr = OxmlElement("w:numPr")
        ilvl = OxmlElement("w:ilvl")
        ilvl.set(qn("w:val"), "0")
        num = OxmlElement("w:numId")
        num.set(qn("w:val"), str(num_id))
        num_pr.extend([ilvl, num])
        existing = p_pr.find(qn("w:numPr"))
        if existing is not None:
            p_pr.remove(existing)
        p_pr.append(num_pr)


def configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    set_style_font(normal, size=11, color=BODY)
    set_style_spacing(normal, before=0, after=6, line=1.25)
    normal.paragraph_format.widow_control = True

    title = doc.styles.add_style("RAG Title", 1)
    title.base_style = doc.styles["Normal"]
    set_style_font(title, size=27, color=INK_BLUE, bold=True)
    set_style_spacing(title, before=0, after=8, line=1.05)

    subtitle = doc.styles.add_style("RAG Subtitle", 1)
    subtitle.base_style = doc.styles["Normal"]
    set_style_font(subtitle, size=13, color=MUTED)
    set_style_spacing(subtitle, before=0, after=18, line=1.12)

    kicker = doc.styles.add_style("RAG Kicker", 1)
    kicker.base_style = doc.styles["Normal"]
    set_style_font(kicker, size=9.5, color=BLUE, bold=True)
    set_style_spacing(kicker, before=0, after=8)

    for name, size, color, before, after in (
        ("Heading 1", 16, BLUE, 18, 10),
        ("Heading 2", 13, BLUE, 14, 7),
        ("Heading 3", 12, DARK_BLUE, 10, 5),
    ):
        style = doc.styles[name]
        set_style_font(style, size=size, color=color, bold=True)
        set_style_spacing(style, before=before, after=after, line=1.12)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.widow_control = True

    doc.styles["Heading 1"].paragraph_format.page_break_before = True

    caption = doc.styles.add_style("RAG Caption", 1)
    caption.base_style = doc.styles["Normal"]
    set_style_font(caption, size=8.5, color=MUTED, italic=True)
    set_style_spacing(caption, before=4, after=4, line=1.0)
    caption.paragraph_format.keep_with_next = True

    small = doc.styles.add_style("RAG Small", 1)
    small.base_style = doc.styles["Normal"]
    set_style_font(small, size=9, color=MUTED)
    set_style_spacing(small, before=0, after=4, line=1.12)

    bullet = doc.styles.add_style("RAG Bullet", 1)
    bullet.base_style = doc.styles["Normal"]
    set_style_font(bullet, size=11, color=BODY)
    set_style_spacing(bullet, before=0, after=4, line=1.25)
    bullet.paragraph_format.left_indent = Inches(0.375)
    bullet.paragraph_format.first_line_indent = Inches(-0.187)

    number = doc.styles.add_style("RAG Number", 1)
    number.base_style = doc.styles["Normal"]
    set_style_font(number, size=11, color=BODY)
    set_style_spacing(number, before=0, after=4, line=1.25)
    number.paragraph_format.left_indent = Inches(0.375)
    number.paragraph_format.first_line_indent = Inches(-0.187)

    code = doc.styles.add_style("RAG Code", 1)
    code.base_style = doc.styles["Normal"]
    set_style_font(code, name=MONO_FONT, east_asia=CN_FONT, size=9, color=INK_BLUE)
    set_style_spacing(code, before=0, after=0, line=1.08)

    table_text = doc.styles.add_style("RAG Table Text", 1)
    table_text.base_style = doc.styles["Normal"]
    set_style_font(table_text, size=8.8, color=BODY)
    set_style_spacing(table_text, before=0, after=0, line=1.05)

    table_head = doc.styles.add_style("RAG Table Head", 1)
    table_head.base_style = doc.styles["Normal"]
    set_style_font(table_head, size=9.0, color=INK_BLUE, bold=True)
    set_style_spacing(table_head, before=0, after=0, line=1.05)


def add_paragraph(
    doc: Document,
    text: str,
    *,
    style: str = "Normal",
    bold_prefix: str | None = None,
):
    paragraph = doc.add_paragraph(style=style)
    if bold_prefix and text.startswith(bold_prefix):
        prefix_run = paragraph.add_run(bold_prefix)
        set_run_font(prefix_run, size=11, color=INK_BLUE, bold=True)
        rest_run = paragraph.add_run(text[len(bold_prefix) :])
        set_run_font(rest_run, size=11, color=BODY)
    else:
        run = paragraph.add_run(text)
        style_font = doc.styles[style]
        size = style_font.font.size.pt if style_font.font.size else 11
        color = None
        if style_font.font.color and style_font.font.color.rgb:
            color = str(style_font.font.color.rgb)
        set_run_font(
            run,
            size=size,
            color=color,
            bold=style_font.font.bold,
            italic=style_font.font.italic,
        )
    return paragraph


def add_bullets(doc: Document, items: Sequence[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph(style="RAG Bullet")
        run = paragraph.add_run(item)
        set_run_font(run, size=11, color=BODY)


def add_numbers(doc: Document, items: Sequence[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph(style="RAG Number")
        run = paragraph.add_run(item)
        set_run_font(run, size=11, color=BODY)


def add_table(
    doc: Document,
    *,
    caption: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    weights: Sequence[float],
    font_size: float = 8.8,
    header_fill: str = HEADER_FILL,
    first_col_bold: bool = False,
) -> None:
    caption_p = doc.add_paragraph(style="RAG Caption")
    caption_run = caption_p.add_run(caption)
    set_run_font(caption_run, size=8.5, color=MUTED, italic=True)
    set_keep_with_next(caption_p)

    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    set_table_borders(table)

    widths = column_widths_from_weights(weights, CONTENT_WIDTH_DXA)
    header_cells = table.rows[0].cells
    for index, header in enumerate(headers):
        cell = header_cells[index]
        cell.text = ""
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        shade_cell(cell, header_fill)
        paragraph = cell.paragraphs[0]
        paragraph.style = doc.styles["RAG Table Head"]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = paragraph.add_run(header)
        set_run_font(run, size=font_size, color=INK_BLUE, bold=True)
    repeat_table_header(table.rows[0])

    for row_index, row_data in enumerate(rows):
        cells = table.add_row().cells
        for col_index, value in enumerate(row_data):
            cell = cells[col_index]
            cell.text = ""
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if row_index % 2 == 1:
                shade_cell(cell, "FAFBFD")
            paragraph = cell.paragraphs[0]
            paragraph.style = doc.styles["RAG Table Text"]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            lines = str(value).split("\n")
            for line_index, line in enumerate(lines):
                if line_index:
                    paragraph.add_run().add_break()
                run = paragraph.add_run(line)
                set_run_font(
                    run,
                    size=font_size,
                    color=INK_BLUE if first_col_bold and col_index == 0 else BODY,
                    bold=first_col_bold and col_index == 0,
                )

    apply_table_geometry(
        table,
        widths,
        table_width_dxa=CONTENT_WIDTH_DXA,
        indent_dxa=TABLE_INDENT_DXA,
        cell_margins_dxa=TABLE_MARGINS,
    )
    doc.add_paragraph(style="RAG Small")


def add_callout(doc: Document, title: str, text: str, *, fill: str = SOFT_FILL) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    set_table_borders(table, color="D9E2EC", size=4)
    cell = table.cell(0, 0)
    cell.text = ""
    shade_cell(cell, fill)
    paragraph = cell.paragraphs[0]
    paragraph.style = doc.styles["Normal"]
    title_run = paragraph.add_run(f"{title}  ")
    set_run_font(title_run, size=10, color=INK_BLUE, bold=True)
    text_run = paragraph.add_run(text)
    set_run_font(text_run, size=10, color=BODY)
    while len(cell.paragraphs) < 2:
        cell.add_paragraph()
    cell.paragraphs[-1].style = doc.styles["RAG Small"]
    apply_table_geometry(
        table,
        [CONTENT_WIDTH_DXA],
        table_width_dxa=CONTENT_WIDTH_DXA,
        indent_dxa=TABLE_INDENT_DXA,
        cell_margins_dxa=TABLE_MARGINS,
    )
    doc.add_paragraph(style="RAG Small")


def add_code_block(doc: Document, text: str) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    set_table_borders(table, color="DCE3EA", size=3)
    cell = table.cell(0, 0)
    cell.text = ""
    shade_cell(cell, LIGHT_FILL)
    paragraph = cell.paragraphs[0]
    paragraph.style = doc.styles["RAG Code"]
    for index, line in enumerate(text.splitlines()):
        if index:
            paragraph.add_run().add_break()
        run = paragraph.add_run(line)
        set_run_font(run, name=MONO_FONT, east_asia=CN_FONT, size=9, color=INK_BLUE)
    apply_table_geometry(
        table,
        [CONTENT_WIDTH_DXA],
        table_width_dxa=CONTENT_WIDTH_DXA,
        indent_dxa=TABLE_INDENT_DXA,
        cell_margins_dxa=TABLE_MARGINS,
    )
    doc.add_paragraph(style="RAG Small")


def configure_header_footer(section) -> None:
    section.different_first_page_header_footer = True
    header = section.header
    paragraph = header.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run("LangGraph RAG 私有文档问答系统  |  技术总结")
    set_run_font(run, size=8.5, color=MUTED)

    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.tab_stops.add_tab_stop(
        Inches(6.5),
        WD_TAB_ALIGNMENT.RIGHT,
    )
    left = paragraph.add_run("内部技术文档  |  2026-09-29")
    set_run_font(left, size=8.5, color=MUTED)
    tab = paragraph.add_run("\t第 ")
    set_run_font(tab, size=8.5, color=MUTED)
    add_field(paragraph, "PAGE")
    suffix = paragraph.add_run(" 页")
    set_run_font(suffix, size=8.5, color=MUTED)

    first_header = section.first_page_header
    first_header.paragraphs[0].text = ""
    first_footer = section.first_page_footer
    first_footer.paragraphs[0].text = ""


def configure_page(section) -> None:
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.right_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)


def add_cover(doc: Document) -> None:
    paragraph = doc.add_paragraph(style="RAG Kicker")
    run = paragraph.add_run("技术总结  |  PRIVATE DOCUMENT RAG")
    set_run_font(run, size=9.5, color=BLUE, bold=True)

    title = doc.add_paragraph(style="RAG Title")
    run = title.add_run("LangGraph RAG\n私有文档问答系统")
    set_run_font(run, size=27, color=INK_BLUE, bold=True)
    title.paragraph_format.line_spacing = 1.03

    subtitle = doc.add_paragraph(style="RAG Subtitle")
    run = subtitle.add_run(
        "基于 Elasticsearch、MinerU 与 AGICTO 的中文制度文档检索、"
        "多轮问答和页码级引用系统"
    )
    set_run_font(run, size=13, color=MUTED)

    add_table(
        doc,
        caption="文档信息",
        headers=["项目", "内容"],
        rows=[
            ["文档类型", "项目技术总结与知识架构说明"],
            ["项目范围", "PDF 入库、层次切片、混合检索、重排、LangGraph 问答、引用高亮、网页端交互"],
            ["数据规模", "当前 10 份制度 PDF；604 个章节；3,334 个检索片段；约 16 万中文字符"],
            ["当前状态", "端到端可运行；98 题评测全部完成且无接口错误"],
            ["数据快照", "2026-09-29"],
        ],
        weights=[1.4, 5.1],
        font_size=9.4,
        first_col_bold=True,
    )

    add_callout(
        doc,
        "核心结论",
        "系统已经形成从 PDF 解析、结构化切片、Elasticsearch 混合检索、"
        "AGICTO 模型推理到原文页码高亮的闭环。检索与回答严格限定在私有文档证据中，"
        "当前仍属于单知识库、匿名会话的可用型骨架。",
    )

    metrics = doc.add_table(rows=1, cols=3)
    metrics.alignment = WD_TABLE_ALIGNMENT.LEFT
    metrics.autofit = False
    set_table_borders(metrics, color="D9E2EC", size=4)
    metric_values = [
        ("98 / 98", "评测完成"),
        ("0%", "非法引用率"),
        ("100%", "引用高亮覆盖"),
    ]
    for index, (value, label) in enumerate(metric_values):
        cell = metrics.cell(0, index)
        cell.text = ""
        shade_cell(cell, HEADER_FILL if index == 0 else SOFT_FILL)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(value)
        set_run_font(run, size=15, color=INK_BLUE, bold=True)
        paragraph.add_run().add_break()
        label_run = paragraph.add_run(label)
        set_run_font(label_run, size=8.5, color=MUTED)
    apply_table_geometry(
        metrics,
        column_widths_from_weights([1, 1, 1], CONTENT_WIDTH_DXA),
        table_width_dxa=CONTENT_WIDTH_DXA,
        indent_dxa=TABLE_INDENT_DXA,
        cell_margins_dxa={"top": 140, "bottom": 140, "start": 120, "end": 120},
    )
    doc.add_paragraph(style="RAG Small")

    note = doc.add_paragraph(style="RAG Small")
    note.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = note.add_run(
        "说明：本文档不包含 API Key、访问令牌或其他密钥。模型、索引名称和运行参数均以当前项目配置为准。"
    )
    set_run_font(run, size=8.5, color=MUTED, italic=True)

def add_navigation(doc: Document) -> None:
    doc.add_heading("内容导航", level=1)
    add_paragraph(
        doc,
        "本文按“目标与约束、知识处理、索引与检索、工作流与治理、技术栈、"
        "运行评测、边界与路线图”的顺序展开，可作为继续开发、演示和交接的基线文档。",
    )
    add_table(
        doc,
        caption="章节索引",
        headers=["编号", "章节", "主要内容"],
        rows=[
            ["1", "执行摘要", "系统价值、当前成效与总体判断"],
            ["2", "项目定位与约束", "私有文档、云端模型、网页应用和范围边界"],
            ["3", "总体架构与数据流", "从 PDF 到答案与高亮的端到端路径"],
            ["4", "PDF 解析与层次切片", "MinerU 归一化与章节优先切分算法"],
            ["5", "Elasticsearch 索引与数据模型", "5 个索引、字段、混合检索与融合"],
            ["6", "LangGraph 状态与节点", "状态字段、13 个节点、条件路由和重试"],
            ["7", "检索与回答治理", "证据约束、引用校验、拒答和页码高亮"],
            ["8", "技术栈与当前配置", "前后端组件、模型和关键运行参数"],
            ["9", "评测结果", "98 题总体指标、分类表现和结论"],
            ["10", "已知边界与风险", "产品质量、工程和生产化风险"],
            ["11", "后续演进路线", "按优先级组织的阶段路线图"],
            ["12", "结论", "项目建设成果与下一步重点"],
            ["附录", "关键代码入口", "后续维护时需要优先阅读的模块"],
        ],
        weights=[0.65, 1.7, 4.15],
        font_size=8.9,
        first_col_bold=True,
    )


def add_executive_summary(doc: Document) -> None:
    doc.add_heading("1. 执行摘要", level=1)
    add_paragraph(
        doc,
        "本项目面向中文 PDF 制度文档，目标是提供一个“只能依据私有文档回答”的"
        "检索增强生成系统。用户可在网页端上传 PDF、连续提问、查看回答中的证据引用，"
        "并通过 PDF 预览定位到对应页码和原文高亮区域。",
    )
    add_paragraph(
        doc,
        "系统将知识处理拆成三条清晰链路：MinerU 负责版面与内容解析；"
        "层次切片器负责把标题层级、段落、表格和坐标信息组织为章节点与检索片段；"
        "LangGraph 负责多轮问题改写、子问题规划、混合检索、重排、证据充分性判断、"
        "答案生成、引用校验、修复与拒答。",
    )
    add_callout(
        doc,
        "当前判断",
        "系统已经达到“可演示、可测试、可继续扩展”的阶段。单跳事实、数值、表格和上下文依赖题表现较强；"
        "跨文档综合、多跳推理、对比与元数据题仍是下一阶段质量提升的重点。98/98 是运行完成率，"
        "不等同于答案语义正确率。",
        fill=CAUTION_FILL,
    )
    add_table(
        doc,
        caption="表 1  当前关键指标",
        headers=["指标", "结果", "含义"],
        rows=[
            ["评测完成度", "98 / 98", "全部请求返回成功，无接口或执行错误"],
            ["引用文档召回", "92.24%", "回答引用命中了多少期望制度文档"],
            ["关键词召回", "87.68%", "回答覆盖测试集关键要点的比例"],
            ["非法引用率", "0%", "所有最终引用均能映射到检索证据"],
            ["引用高亮覆盖", "100%", "最终引用均携带可定位的 PDF 坐标信息"],
            ["平均延迟", "16.18 秒", "并发度为 3 时的端到端平均耗时"],
        ],
        weights=[1.45, 1.2, 3.85],
        font_size=8.8,
        first_col_bold=True,
    )
    add_paragraph(
        doc,
        "系统最重要的工程价值不是“接了几个模型”，而是把可信约束落到状态、路由、"
        "引用结构和前端交互中：没有足够证据就拒答；非法证据编号修复失败后拒答；"
        "最终返回的每个引用都包含文档、章节、页码、原文片段和坐标。",
    )


def add_positioning(doc: Document) -> None:
    doc.add_heading("2. 项目定位与约束", level=1)
    add_paragraph(
        doc,
        "项目定位是“私有制度知识库的检索与问答入口”，不是通用聊天机器人，"
        "也不是覆盖所有企业知识管理能力的完整平台。所有回答必须优先服从私有文档边界，"
        "云端模型只接收完成当前问答所需的检索片段和对话上下文。",
    )
    add_table(
        doc,
        caption="表 2  核心约束与当前处理方式",
        headers=["约束", "当前处理方式", "影响"],
        rows=[
            ["文档仅包含 PDF", "上传接口拒绝非 PDF 文件", "入库格式简单，但暂不支持 Word、网页、数据库等来源"],
            ["当前不包含扫描件", "MinerU 直接解析文本型 PDF 和版面结构", "不依赖 OCR；扫描件质量暂不做承诺"],
            ["中文制度文档", "检索字段使用中文文本；可配置 IK 分词", "当前 ES 使用 standard analyzer，中文召回仍可工作但可继续增强"],
            ["严格基于私有文档", "系统提示限制只依据证据回答；证据不足则拒答", "降低外部知识幻觉，但依赖召回质量"],
            ["允许向云端发送检索片段", "片段、问题和最近对话发送给 AGICTO", "满足质检环境使用；如更敏感需增加脱敏或私有模型"],
            ["简单登录或匿名会话", "HttpOnly Cookie 生成匿名 session", "可隔离会话记录；尚无账号体系"],
            ["暂不实现文档权限", "所有用户共享同一知识库", "当前适合个人或受控演示；生产前必须补权限过滤"],
        ],
        weights=[1.45, 2.75, 2.3],
        font_size=8.55,
        first_col_bold=True,
    )
    doc.add_heading("2.1 范围内目标", level=2)
    add_bullets(
        doc,
        [
            "完成 PDF 上传、MinerU 云解析、层次切片、向量化与 Elasticsearch 入库。",
            "支持单轮和多轮中文问答，并能够把依赖上下文的问题改写为独立检索问题。",
            "支持 BM25 与向量检索融合、重排、多子问题检索和证据充分性判断。",
            "答案中的引用必须映射到原文、页码和坐标，可在网页端高亮。",
            "对证据不足或引用不可修复的情况进行明确拒答。",
        ],
    )
    doc.add_heading("2.2 暂不承诺的能力", level=2)
    add_bullets(
        doc,
        [
            "跨用户文档隔离、角色权限和管理员审计。",
            "扫描件 OCR、复杂图表理解和跨页表格结构化重建。",
            "全量知识图谱、关系推理或外部网页检索。",
            "生产级高可用、分布式任务队列、模型调用成本监控和多租户部署。",
        ],
    )


def add_architecture(doc: Document) -> None:
    doc.add_heading("3. 总体架构与数据流", level=1)
    add_paragraph(
        doc,
        "总体架构可以概括为“离线入库链路 + 在线问答链路 + 前端溯源链路”。"
        "离线链路把 PDF 转为可检索的章节与片段；在线链路通过 LangGraph 将检索、"
        "重排、生成和引用治理串成可控状态机；前端链路负责对话展示和 PDF 定位。",
    )
    add_table(
        doc,
        caption="表 3  端到端数据流",
        headers=["阶段", "输入", "处理", "输出"],
        rows=[
            ["1. 上传", "PDF 文件", "校验扩展名，保存文件，生成 doc_id/version_id", "待解析文档记录"],
            ["2. 解析", "PDF", "MinerU 返回内容列表、页面尺寸和 bbox", "标准化 ParsedBlock 列表"],
            ["3. 切片", "ParsedBlock", "按标题构建章节树；章节过长时按 500 字切分并重叠 15%", "SectionNode + ChunkRecord"],
            ["4. 向量化", "Chunk 文本", "调用嵌入模型，批量生成 1024 维向量", "带 embedding 的片段"],
            ["5. 入库", "章节与片段", "写入 documents、sections、chunks 索引", "可检索知识库"],
            ["6. 在线检索", "用户问题", "问题改写、子问题规划、BM25 + kNN、RRF 融合、重排", "Top-K 证据片段"],
            ["7. 生成与治理", "证据与历史", "生成答案、校验引用、必要时修复或拒答", "带引用的最终答案"],
            ["8. 溯源", "引用对象", "加载 PDF 页面并叠加坐标高亮", "页码级原文预览"],
        ],
        weights=[1.0, 1.2, 2.8, 1.5],
        font_size=8.4,
        first_col_bold=True,
    )
    add_table(
        doc,
        caption="表 4  运行组件与职责",
        headers=["层", "组件", "职责"],
        rows=[
            ["前端", "React + Vite + react-pdf", "上传、会话、引用列表、PDF 页码定位与 bbox 高亮"],
            ["API", "FastAPI", "匿名会话、文件接口、文档列表、健康检查、聊天入口"],
            ["编排", "LangGraph", "状态机、条件路由、检索重试、引用修复与拒答"],
            ["检索", "Elasticsearch", "文档、章节、片段、会话和轮次持久化，BM25 + kNN"],
            ["解析", "MinerU 云 API", "PDF 内容、表格、页序和坐标解析"],
            ["模型", "AGICTO", "问题改写、子问题规划、答案生成、引用修复、嵌入与重排"],
        ],
        weights=[0.85, 1.8, 3.85],
        font_size=8.65,
        first_col_bold=True,
    )


def add_parsing_and_chunking(doc: Document) -> None:
    doc.add_heading("4. PDF 解析与层次切片", level=1)
    doc.add_heading("4.1 MinerU 解析与归一化", level=2)
    add_paragraph(
        doc,
        "解析适配器支持 MinerU 云 API，也保留本地 CLI 路径。云 API 流程为申请上传地址、"
        "上传 PDF、轮询解析状态、下载结果压缩包并安全解压。解析完成后，系统读取 "
        "content_list JSON，并结合 layout.json 中的页面尺寸统一坐标。",
    )
    add_bullets(
        doc,
        [
            "只保留正文、标题、表格、公式、列表、图注等有效块，过滤页眉、页脚和页码。",
            "标题识别依据 text_level 或 level，并限制在 1 到 6 级。",
            "表格 HTML 转为带“|”分隔的行文本，尽量保留单元格内容。",
            "bbox 若为归一化坐标，则按页面宽高转换到实际坐标。",
            "每个 ParsedBlock 保留 block_id、类型、文本、页码、bbox、页面尺寸和原始顺序。",
        ],
    )

    doc.add_heading("4.2 层次切片算法", level=2)
    add_paragraph(
        doc,
        "切片采用“章节优先、长度兜底”的两层策略。第一步不是直接按字数切，"
        "而是先根据标题层级建立父子章节；第二步只对内容过长的章节做文本分片。"
        "这样既能保留制度条款的章节语义，也能控制单个检索单元的上下文长度。",
    )
    add_numbers(
        doc,
        [
            "以文档标题创建根章节；遇到标题块时，按标题层级弹出栈中较深节点并建立父子关系。",
            "标题块本身用于组织章节，不进入章节正文；正文块归属最近的当前章节。",
            "若章节正文总长度不超过 1,000 字，则尽量生成一个完整章节片段。",
            "若章节超过 1,000 字，将连续文本块聚合到约 500 字；超出时按 500 字切片。",
            "相邻切片重叠为 500 × 15% = 75 字，避免边界语义断裂。",
            "表格、公式和图片视为原子块，不跨块切分，避免结构内容被腰斩。",
            "全部片段按顺序链接 prev_chunk_id 与 next_chunk_id，为后续上下文扩展预留能力。",
        ],
    )
    add_table(
        doc,
        caption="表 5  切片参数与行为",
        headers=["参数/字段", "当前值", "作用"],
        rows=[
            ["chunk_target_chars", "500", "文本片段目标长度"],
            ["chunk_max_section_chars", "1,000", "章节是否需要再次切分的阈值"],
            ["chunk_overlap_ratio", "0.15", "相邻文本片段重叠比例"],
            ["实际 overlap", "75 字", "由 500 × 15% 计算，向下取整"],
            ["原子块类型", "table / formula / image", "不拆分，单独生成片段"],
            ["chunker_version", "hierarchical-v1", "切片算法版本标识"],
            ["source_spans", "页码、bbox、页宽高、quote", "支持引用高亮和原文核验"],
        ],
        weights=[1.65, 1.35, 3.5],
        font_size=8.65,
        first_col_bold=True,
    )
    add_callout(
        doc,
        "设计取舍",
        "章节级切片保留制度语境，500 字兜底控制模型上下文；15% 重叠降低边界丢词风险，"
        "但会带来少量重复检索结果。若后续强调精确条款召回，应增加父子检索或按“条/款”再切一层。",
    )


def add_elasticsearch(doc: Document) -> None:
    doc.add_heading("5. Elasticsearch 索引与检索模型", level=1)
    add_paragraph(
        doc,
        "Elasticsearch 同时承担知识库、版本控制、会话记忆和轮次记录四项职责。"
        "知识侧使用 documents、sections、chunks 三个索引建立“文档-章节-片段”"
        "层次；对话侧使用 conversations 和 turns 保存会话与消息。",
    )
    add_table(
        doc,
        caption="表 6  当前索引快照",
        headers=["索引", "用途", "文档数", "关键 ID"],
        rows=[
            ["rag_documents", "文档元数据与解析状态", "10", "doc_id"],
            ["rag_sections", "章节树、标题路径和页范围", "604", "section_id"],
            ["rag_chunks", "检索片段、向量、页码坐标和邻居关系", "3,334", "chunk_id"],
            ["rag_conversations", "会话对象、最近消息时间与状态", "404", "conversation_id"],
            ["rag_turns", "用户和助手消息、引用与模型信息", "814", "turn_id"],
        ],
        weights=[1.45, 3.05, 0.9, 1.1],
        font_size=8.75,
        first_col_bold=True,
    )
    doc.add_heading("5.1 rag_chunks 关键字段", level=2)
    add_table(
        doc,
        caption="表 7  片段索引中的核心字段",
        headers=["字段", "类型", "设计意图"],
        rows=[
            ["chunk_id", "keyword", "片段唯一主键，由 section_id + chunk_index 组成"],
            ["doc_id / version_id", "keyword", "关联文档和版本，支持重新入库与版本失效"],
            ["document_title", "text + keyword", "正文召回与结果标题匹配"],
            ["section_id", "keyword", "回连章节树与标题路径"],
            ["text", "text", "BM25 主检索字段，权重最高"],
            ["heading_path", "text", "标题路径检索，强调章节语义"],
            ["page_start / page_end", "integer", "构建引用页码范围"],
            ["source_spans", "nested", "保存页码、bbox、页面尺寸和 quote，用于高亮"],
            ["embedding", "dense_vector(1024)", "余弦向量检索；模型可配置"],
            ["prev/next_chunk_id", "keyword", "相邻片段扩展与上下文拼接"],
            ["is_current", "boolean", "只检索当前有效版本"],
        ],
        weights=[1.6, 1.35, 3.55],
        font_size=8.55,
        first_col_bold=True,
    )

    doc.add_heading("5.2 混合检索与融合", level=2)
    add_numbers(
        doc,
        [
            "BM25 使用 multi_match，字段权重为 text^3、heading_path^2、document_title。",
            "向量检索使用 kNN，候选数至少为 size × 4 且不少于 50，过滤 is_current=true。",
            "两路结果使用 Reciprocal Rank Fusion 融合，单路贡献为 1 / (60 + rank)。",
            "多子问题并行检索后按 chunk_id 合并；同一片段命中越多子问题，排序加成越高。",
            "合并得分为 max(query_scores) + 0.1 × (命中子问题数 - 1)。",
            "候选片段进入重排模型，最终保留 Top 8 作为证据。",
        ],
    )
    add_code_block(
        doc,
        "RRF(chunk) = Σ 1 / (60 + rank_source(chunk))\n"
        "multi_query_score = max(query_scores) + 0.1 × (matched_query_count - 1)",
    )
    add_callout(
        doc,
        "检索边界",
        "当前每条子问题默认召回 30 个候选，重排后最多 8 条。对跨文档综合题，"
        "真正的瓶颈往往不是单条片段不相关，而是不同条款没有同时进入最终 8 条证据。"
        "因此后续应重点考虑按子问题配额、父章节扩展和文档多样性约束。",
        fill=CAUTION_FILL,
    )


def add_langgraph(doc: Document) -> None:
    doc.add_heading("6. LangGraph 状态、节点与路由", level=1)
    add_paragraph(
        doc,
        "LangGraph 工作流使用 RAGState 作为共享状态。节点不直接修改可变对象，"
        "而是返回需要合并到状态的字段；trace 使用追加方式记录执行轨迹，"
        "便于评测时还原每一步。",
    )
    add_table(
        doc,
        caption="表 8  RAGState 字段分组",
        headers=["字段组", "代表字段", "用途"],
        rows=[
            ["请求与上下文", "conversation_id, session_id, request_id, current_query, messages", "标识请求并装载最近 8 轮对话"],
            ["问题理解", "conversation_summary, standalone_query, retrieval_queries, missing_retrieval_queries", "多轮改写与多子问题规划"],
            ["检索结果", "retrieved_candidates, reranked_evidence, retrieval_round", "缓存候选、重排证据与检索重试状态"],
            ["证据判断", "evidence_sufficient, insufficiency_reason, context_pack, evidence_map", "判断是否可答，并构造仅含 E-id 的证据包"],
            ["生成与引用", "draft_answer, final_answer, citations, citation_check", "生成、校验和最终输出"],
            ["修复与拒答", "invalid_evidence_ids, valid_evidence_ids, citation_repair_feedback, repair_round, abstain_reason", "控制一次引用修复与失败拒答"],
            ["执行状态", "status, error, trace", "接口状态、错误和节点轨迹"],
        ],
        weights=[1.2, 2.75, 2.55],
        font_size=8.35,
        first_col_bold=True,
    )
    add_table(
        doc,
        caption="表 9  节点输入与输出",
        headers=["节点", "主要输入", "主要输出"],
        rows=[
            ["load_context", "conversation_id, session_id", "messages，并重置 retrieval_round 与 repair_round"],
            ["contextualize_query", "current_query, messages", "standalone_query"],
            ["plan_retrieval", "standalone_query", "1 到 3 条 retrieval_queries"],
            ["retrieve", "retrieval_queries, embedding", "BM25+kNN 融合后的 retrieved_candidates"],
            ["rerank", "retrieval_queries, candidates", "按重排分数排序的 reranked_evidence"],
            ["assess_evidence", "evidence, 对应来源的阈值", "evidence_sufficient、缺口原因和缺失子问题"],
            ["rewrite_for_retry", "缺失子问题和原查询", "补充同义词后的 retrieval_queries，并发起第二轮检索"],
            ["compose_context", "reranked_evidence", "E1...En 的 context_pack 与 evidence_map"],
            ["generate", "standalone_query, context_pack, messages", "带 [E-id] 标记的 draft_answer"],
            ["verify_citations", "draft_answer, evidence_map", "citation_check、citations、final_answer"],
            ["repair_citations", "非法引用和合法证据集合", "清洗或重绑后的 draft_answer，最多一次"],
            ["abstain", "证据不足或修复失败原因", "固定拒答文本和 abstain_reason"],
            ["persist_turn", "问题、最终答案、引用", "写入 turn 和 conversation 索引，状态完成"],
        ],
        weights=[1.35, 2.5, 2.65],
        font_size=8.15,
        first_col_bold=True,
    )
    doc.add_heading("6.1 主路由", level=2)
    add_code_block(
        doc,
        "START → load_context → contextualize_query → plan_retrieval\n"
        "      → retrieve → rerank → assess_evidence\n"
        "\n"
        "assess_evidence\n"
        "  ├─ 证据充分 → compose_context → generate → verify_citations\n"
        "  ├─ 证据不足且未重试 → rewrite_for_retry → retrieve\n"
        "  └─ 二次仍不足 → abstain → persist_turn → END\n"
        "\n"
        "verify_citations\n"
        "  ├─ 合法 → persist_turn → END\n"
        "  ├─ 非法且未修复 → repair_citations → verify_citations\n"
        "  └─ 修复后仍非法 → abstain → persist_turn → END",
    )
    add_paragraph(
        doc,
        "多轮问答有两层上下文控制：加载最近 8 轮消息用于问题改写；生成答案时只携带最近 4 轮消息。"
        "该设计减少无关历史对回答和引用范围的干扰。LangGraph 编译时使用 MemorySaver 作为检查点，"
        "当前适合单实例开发与演示，但不适合多实例生产部署。",
    )


def add_governance(doc: Document) -> None:
    doc.add_heading("7. 检索与回答治理", level=1)
    add_paragraph(
        doc,
        "可信问答的关键不是让模型“更自信”，而是把不可信结果挡在响应之外。"
        "系统把检索证据转成 E1、E2 等编号，并要求模型在事实性结论后引用这些编号。"
        "最终接口返回的不是模型临时生成的页码，而是证据对象中真实保存的文档、章节、页码和坐标。",
    )
    add_table(
        doc,
        caption="表 10  回答治理规则",
        headers=["控制点", "规则", "失败行为"],
        rows=[
            ["证据边界", "系统提示要求只依据提供的证据回答，不得使用外部知识补全", "证据不足时回答无法确认"],
            ["证据最低分", "重排最高分达到阈值，且所有子问题都有达标证据", "进入一次查询改写和重试"],
            ["引用存在性", "最终答案至少包含一个 [E-id]", "进入引用修复"],
            ["引用合法性", "所有 [E-id] 均必须存在于 evidence_map", "移除非法标记或重绑到合法证据"],
            ["修复次数", "最多修复一次，修复后再次执行校验", "仍失败则拒答且不返回引用"],
            ["引用对象", "由 evidence_map 构造，不由模型生成", "避免虚构文档名、页码和链接"],
            ["高亮坐标", "source_spans 保存页码、bbox、页宽高和 quote", "前端叠加与页面坐标一致的高亮层"],
        ],
        weights=[1.2, 3.2, 2.1],
        font_size=8.5,
        first_col_bold=True,
    )
    doc.add_heading("7.1 引用高亮链路", level=2)
    add_numbers(
        doc,
        [
            "检索片段携带一个或多个 SourceSpan；每个 span 对应一段原文及其页码和 bbox。",
            "答案生成只使用 [E1] 等抽象编号，不直接拼接页码或链接。",
            "引用校验通过后，后端按 evidence_id 还原 doc_id、title、heading_path、page_start/page_end 和 source_spans。",
            "前端 react-pdf 加载原 PDF 页面，并将 bbox 按页面宽高换算为百分比坐标。",
            "高亮层与 PDF 页面同宽同高叠加，用户点击引用后可查看对应原文和引用片段。",
        ],
    )
    add_callout(
        doc,
        "精度含义",
        "当前引用是“页码级 + 坐标级”定位，而非条款编号级结构化引用。"
        "当 MinerU 返回的 bbox 准确时，高亮可精确定位原文；若模型把正确事实绑定到相邻但不充分的证据，"
        "引用合法性仍会通过。因此后续需要增加“主张-证据蕴含”校验，而不只是编号合法性校验。",
        fill=CAUTION_FILL,
    )


def add_stack(doc: Document) -> None:
    doc.add_heading("8. 技术栈与当前配置", level=1)
    add_table(
        doc,
        caption="表 11  技术栈",
        headers=["层次", "技术", "当前用途"],
        rows=[
            ["后端运行时", "Python 3.12 + uv", "依赖管理与本地运行"],
            ["API", "FastAPI + Uvicorn", "REST API、上传、聊天、文件访问和健康检查"],
            ["工作流", "LangGraph", "状态图、条件边、检查点和执行轨迹"],
            ["数据模型", "Pydantic", "文档、片段、引用、聊天请求响应校验"],
            ["检索", "Elasticsearch 8 Async Client", "BM25、kNN、nested source_spans、会话持久化"],
            ["解析", "MinerU API/CLI", "文本、标题、表格、公式和坐标"],
            ["模型网关", "AGICTO", "Chat、Embedding、Rerank"],
            ["前端", "React + TypeScript + Vite", "上传、对话、引用与状态展示"],
            ["PDF", "react-pdf", "按页渲染和 bbox 高亮"],
            ["测试", "pytest + ruff", "切片、节点、解析和评测逻辑校验"],
        ],
        weights=[1.15, 2.25, 3.1],
        font_size=8.55,
        first_col_bold=True,
    )
    add_table(
        doc,
        caption="表 12  当前模型配置",
        headers=["角色", "模型", "说明"],
        rows=[
            ["Chat / Generate", "qwen-plus", "答案生成与引用修复的主模型"],
            ["Fast / Rewrite", "qwen-plus", "多轮问题改写、子问题规划和检索重试"],
            ["Embedding", "text-embedding-v4", "1024 维向量，用于 kNN 检索"],
            ["Rerank", "qwen3-rerank", "对候选片段做相关性重排，最终 Top 8"],
            ["MinerU", "vlm", "云 API 解析模式，中文 PDF"],
        ],
        weights=[1.4, 1.65, 3.45],
        font_size=8.8,
        first_col_bold=True,
    )
    add_table(
        doc,
        caption="表 13  关键运行参数",
        headers=["参数", "当前值", "影响"],
        rows=[
            ["retrieval_candidates", "30", "每条检索查询的候选数量"],
            ["rerank_top_k", "8", "进入生成上下文的最大证据数"],
            ["min_rerank_score / min_fusion_score", "0.25", "按证据来源分别判断是否充分"],
            ["embedding_dimensions", "1024", "与 ES dense_vector 维度必须一致"],
            ["embedding batch", "10", "入库向量化的批大小"],
            ["recent turns", "8", "问题改写使用的历史消息上限"],
            ["generation turns", "4", "生成提示携带的历史消息上限"],
            ["session lifetime", "30 天", "匿名 Cookie 会话有效期"],
            ["checkpointer", "MemorySaver", "开发型内存检查点，进程重启后丢失"],
        ],
        weights=[1.7, 1.25, 3.55],
        font_size=8.65,
        first_col_bold=True,
    )


def add_evaluation(doc: Document) -> None:
    doc.add_heading("9. 评测结果", level=1)
    add_paragraph(
        doc,
        "评测集包含 98 道中文制度问答，覆盖单跳事实、单跳数值、多跳推理、"
        "多意图、跨文档综合、否定边界、表格提取、元数据、干扰项和上下文依赖等类型。"
        "测试脚本并发调用聊天 API，统计关键词召回、引用文档召回、引用高亮、"
        "证据充分性、修复记录和端到端延迟。",
    )
    add_callout(
        doc,
        "指标解释",
        "keyword_recall 检查回答是否出现测试集关键词；citation_doc_recall 检查引用是否覆盖期望文档。"
        "两者都是可自动化的代理指标，不能完全替代人工语义正确性、引用充分性和回答简洁度评审。",
        fill=CAUTION_FILL,
    )
    add_table(
        doc,
        caption="表 14  总体评测指标",
        headers=["指标", "结果", "评价"],
        rows=[
            ["完成数 / 错误数", "98 / 0", "运行稳定性已达标"],
            ["引用出现率", "100%", "所有回答均附引用"],
            ["引用高亮率", "100%", "所有引用均含可用坐标"],
            ["非法引用率", "0%", "最终引用编号均可映射到证据"],
            ["引用文档召回宏平均", "92.24%", "整体较好，跨文档题拉低均值"],
            ["关键词召回宏平均", "87.68%", "数值与事实题较强，类比与元数据较弱"],
            ["所有期望文档均被引用率", "83.67%", "仍有约 16% 问题漏引至少一份制度"],
            ["证据充分率", "100%", "当前 98 题均未拒答"],
            ["多意图证据覆盖", "100%", "所有子问题均被判定有证据"],
            ["修复成功率", "100%", "发生引用修复的记录最终均生成有效引用"],
            ["回答文本相似度", "22.87%", "该指标对改写和详细回答不敏感，仅作辅助"],
            ["平均延迟", "16.18 秒", "受并发、重排和模型生成影响明显"],
            ["P50 / P95 延迟", "12.08 / 43.19 秒", "尾延迟偏高，生产化需要超时与流式输出"],
        ],
        weights=[1.55, 1.15, 3.8],
        font_size=8.45,
        first_col_bold=True,
    )
    add_table(
        doc,
        caption="表 15  分类表现",
        headers=["类型", "题数", "关键词召回", "引用文档召回", "平均延迟"],
        rows=[
            ["单跳-事实", "20", "94.58%", "100%", "10.49 秒"],
            ["单跳-数值", "15", "96.67%", "97.78%", "8.55 秒"],
            ["表格提取", "5", "86.67%", "100%", "19.72 秒"],
            ["上下文依赖型", "4", "100%", "100%", "6.30 秒"],
            ["模糊指代型", "4", "100%", "100%", "13.09 秒"],
            ["否定边界", "6", "100%", "91.67%", "10.24 秒"],
            ["反问型", "4", "68.75%", "100%", "13.58 秒"],
            ["元数据", "6", "66.67%", "88.89%", "16.27 秒"],
            ["干扰项", "6", "78.02%", "91.67%", "23.43 秒"],
            ["多意图型", "4", "88.75%", "87.50%", "18.85 秒"],
            ["多跳推理", "8", "82.26%", "84.38%", "25.34 秒"],
            ["对比型", "4", "70.00%", "100%", "31.86 秒"],
            ["跨文档综合", "12", "81.79%", "67.87%", "26.03 秒"],
        ],
        weights=[1.55, 0.65, 1.2, 1.3, 1.1],
        font_size=8.35,
        first_col_bold=True,
    )
    doc.add_heading("9.1 结果解读", level=2)
    add_bullets(
        doc,
        [
            "强项是单跳事实、单跳数值、表格和上下文改写；这些任务通常能在少量高相关片段中完成。",
            "跨文档综合题的引用文档召回约为 67.87%，说明最终 Top 8 证据经常只覆盖部分制度。",
            "多跳推理和对比题延迟较高，主要因为子问题规划、多个重排请求和更长的模型生成。",
            "元数据题的自动关键词指标偏低，部分原因是答案强调“查哪份制度、哪一章”，不一定逐字复现关键词。",
            "P95 延迟 43.19 秒对交互体验偏慢，异步排队、多个检索子问题、重排和长回答共同贡献了尾延迟。",
        ],
    )


def add_risks(doc: Document) -> None:
    doc.add_heading("10. 已知边界与风险", level=1)
    add_table(
        doc,
        caption="表 16  主要边界与风险",
        headers=["类别", "当前问题", "影响", "建议优先级"],
        rows=[
            ["权限", "所有文档共享同一知识库，无文档级过滤", "多用户场景下会越权检索", "高"],
            ["会话", "仅匿名 Cookie，无账号和会话管理界面", "难以审计和保留用户资产", "中"],
            ["引用充分性", "只校验 [E-id] 合法，不校验事实是否被证据蕴含", "可能出现“引用正确但支持不足”", "高"],
            ["跨文档召回", "固定 Top 8 容易牺牲文档多样性", "综合题漏引制度", "高"],
            ["解析质量", "依赖 MinerU bbox 和表格还原", "复杂表格或跨页表格可能错位", "中"],
            ["版本管理", "片段有 version，但文档级历史界面尚未建立", "难以查看更新差异", "中"],
            ["检查点", "MemorySaver 仅内存保存", "多实例或重启后状态丢失", "中"],
            ["可观测性", "trace 可返回，但缺少集中日志、成本和成功率面板", "定位线上问题成本高", "中"],
            ["安全", "证据片段发送云端，密钥和访问边界需持续管控", "敏感制度环境存在合规风险", "高"],
            ["评测", "自动指标不能完全替代语义正确性判断", "高分可能掩盖表达或推理问题", "高"],
        ],
        weights=[0.85, 2.25, 2.45, 0.95],
        font_size=8.15,
        first_col_bold=True,
    )
    add_callout(
        doc,
        "最重要的三项",
        "第一，文档权限或至少知识库隔离；第二，主张级证据校验；第三，跨文档证据配额与父章节扩展。"
        "这三点比继续增加界面功能更能决定系统能否从演示走向可信使用。",
        fill=CAUTION_FILL,
    )


def add_roadmap(doc: Document) -> None:
    doc.add_heading("11. 后续演进路线", level=1)
    add_table(
        doc,
        caption="表 17  建议路线图",
        headers=["阶段", "目标", "关键工作", "验收指标"],
        rows=[
            [
                "近期：稳定性与可信度",
                "把当前演示型骨架变为可持续试用版本",
                "增加模型调用超时/重试与降级；集中日志；补充人工语义评测；引用主张级校验原型",
                "失败可解释；P95 延迟下降；人工正确性有基线",
            ],
            [
                "中期：检索质量",
                "解决漏引、跨文档覆盖和多跳聚合",
                "按子问题配额召回；父章节扩展；文档多样性约束；按条款细粒度索引；查询分解结果聚合",
                "跨文档引用召回 > 85%；多跳关键词召回 > 90%",
            ],
            [
                "中期：产品能力",
                "形成可管理的知识库",
                "账号登录；文档权限；知识库选择；会话列表；文档版本与删除；上传进度",
                "用户只能访问授权文档；会话可管理和审计",
            ],
            [
                "远期：生产化",
                "支持多实例、可观测和成本治理",
                "Redis/PostgreSQL 检查点；异步任务队列；指标与告警；模型路由和预算；灰度评测",
                "高可用；可追踪；单位问答成本可计算",
            ],
        ],
        weights=[1.3, 1.35, 2.45, 1.4],
        font_size=8.0,
        first_col_bold=True,
    )
    doc.add_heading("11.1 优先修复建议", level=2)
    add_numbers(
        doc,
        [
            "为每次请求记录检索子问题、候选文档分布、重排分数、最终证据、模型耗时和 token 使用。",
            "把最终证据从固定 Top 8 改为“每个子问题至少 N 条 + 全局限额”，并增加文档多样性约束。",
            "为引用校验增加“答案句 → 证据片段”的支持度检查，低支持句必须删除或拒答。",
            "增加父章节扩展，在片段命中后补充父标题与相邻片段，改善跨条款推理。",
            "为匿名会话提供清理和导出入口，为后续账号、知识库和权限模型预留数据结构。",
            "建立人工标注集，至少抽样评估事实正确性、引用充分性、完整性和拒答正确性。",
        ],
    )


def add_conclusion(doc: Document) -> None:
    doc.add_heading("12. 结论", level=1)
    add_paragraph(
        doc,
        "本项目已经完成一条完整的私有文档 RAG 闭环：中文 PDF 经 MinerU 解析，"
        "按章节和长度形成层次片段，写入 Elasticsearch 并使用 BM25 + 向量 + 重排检索；"
        "LangGraph 将多轮改写、子问题规划、证据判断、生成、引用校验、修复和拒答组织为显式状态机；"
        "前端能够展示回答、引用页码和 PDF 高亮。",
    )
    add_paragraph(
        doc,
        "当前系统适合作为个人或受控环境中的可用型原型。它已经验证了“严格基于私有文档”"
        "这一约束可以落到检索、生成和引用结构上，但还没有解决权限隔离、主张级证据验证、"
        "跨文档综合覆盖和生产级可观测性。下一阶段的重点应从“增加功能”转向“提升可信度与可运营性”，"
        "尤其是文档权限、跨文档召回和引用充分性。",
    )
    add_callout(
        doc,
        "建议的下一步",
        "先落地请求级可观测性、跨文档证据配额和主张级引用校验；随后再补账号、权限和多知识库。"
        "这样做能先解决回答质量问题，再扩展用户规模，避免在核心可信度尚未稳定时过早增加平台复杂度。",
    )


def add_appendix(doc: Document) -> None:
    doc.add_heading("附录 A  关键代码入口", level=1)
    add_table(
        doc,
        caption="表 A1  维护地图",
        headers=["模块", "关键文件", "职责"],
        rows=[
            ["LangGraph 工作流", "backend/rag_app/graph/workflow.py", "节点注册、边和条件路由"],
            ["工作流状态", "backend/rag_app/graph/state.py", "RAGState 字段定义"],
            ["工作流节点", "backend/rag_app/graph/nodes.py", "检索、重排、生成、引用校验、修复和拒答"],
            ["Elasticsearch", "backend/rag_app/services/elasticsearch.py", "索引结构、混合检索、RRF、会话轮次"],
            ["层次切片", "backend/rag_app/services/chunking.py", "章节树、500 字切片、75 字重叠、邻居链接"],
            ["数据模型", "backend/rag_app/models/document.py", "ParsedBlock、SectionNode、ChunkRecord、SourceSpan"],
            ["MinerU", "backend/rag_app/services/mineru.py", "云解析、内容列表归一化、表格和 bbox 处理"],
            ["AGICTO", "backend/rag_app/services/agicto.py", "Chat、Embedding、Rerank 和提示词"],
            ["入库服务", "backend/rag_app/services/ingestion.py", "上传、解析、向量化、写入和版本失效"],
            ["API", "backend/rag_app/api/routes.py", "健康检查、文档、文件和聊天接口"],
            ["前端首页", "frontend/src/App.tsx", "上传、会话、引用选择和布局"],
            ["PDF 高亮", "frontend/src/components/PdfPreview.tsx", "react-pdf 页面渲染与 bbox 叠加"],
            ["评测脚本", "scripts/evaluate_rag.py", "并发评测、指标聚合和报告生成"],
        ],
        weights=[1.2, 2.35, 2.95],
        font_size=8.25,
        first_col_bold=True,
    )
    doc.add_heading("附录 B  术语", level=2)
    add_table(
        doc,
        caption="表 B1  常用术语",
        headers=["术语", "含义"],
        rows=[
            ["SectionNode", "文档标题层级对应的章节节点，保存父子关系、标题路径和页范围"],
            ["ChunkRecord", "进入 Elasticsearch 的检索片段，保存文本、向量、页码坐标和邻居关系"],
            ["SourceSpan", "用于引用定位的原文范围，包含页码、bbox、页面宽高和 quote"],
            ["RRF", "Reciprocal Rank Fusion，多路检索结果的排名融合方法"],
            ["Evidence ID", "上下文中的 E1、E2 等证据编号，用于约束模型引用"],
            ["Abstain", "证据不足或引用修复失败时拒绝回答，而不是使用外部知识补全"],
            ["Standalone Query", "把依赖历史的多轮问题改写为可独立检索的问题"],
        ],
        weights=[1.5, 5.0],
        font_size=8.7,
        first_col_bold=True,
    )


def build_document() -> None:
    doc = Document()
    configure_styles(doc)
    configure_numbering(doc)
    configure_page(doc.sections[0])
    configure_header_footer(doc.sections[0])

    core = doc.core_properties
    core.title = "LangGraph RAG 私有文档问答系统技术总结"
    core.subject = "知识架构、技术栈、实现路径与评测"
    core.author = "Codex"
    core.keywords = "LangGraph, RAG, Elasticsearch, MinerU, AGICTO, Private Documents"
    core.comments = "不含密钥；数据快照为 2026-09-29。"

    add_cover(doc)
    add_navigation(doc)
    add_executive_summary(doc)
    add_positioning(doc)
    add_architecture(doc)
    add_parsing_and_chunking(doc)
    add_elasticsearch(doc)
    add_langgraph(doc)
    add_governance(doc)
    add_stack(doc)
    add_evaluation(doc)
    add_risks(doc)
    add_roadmap(doc)
    add_conclusion(doc)
    add_appendix(doc)

    doc.save(OUTPUT_PATH)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    build_document()
