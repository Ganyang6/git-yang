#!/usr/bin/env python3
"""Convert MES edge AI paper from MD to DOCX"""
import re
import docx
from docx import Document
from docx.shared import Pt, Inches, Cm, Emu, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml


def create_document():
    """Create document with proper page setup"""
    doc = Document()

    # Page setup
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Inches(0.95)
    section.bottom_margin = Inches(0.95)
    section.left_margin = Inches(1.02)
    section.right_margin = Inches(1.02)

    return doc


def set_run_font(run, font_name_ascii='宋体', font_name_east='宋体', size=Pt(12), bold=False):
    """Set font for a run"""
    run.font.name = font_name_ascii
    run.font.size = size
    run.font.bold = bold
    r = run._element
    rPr = r.find(qn('w:rPr'))
    if rPr is None:
        rPr = parse_xml(f'<w:rPr {nsdecls("w")}></w:rPr>')
        r.insert(0, rPr)
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = parse_xml(f'<w:rFonts {nsdecls("w")}></w:rFonts>')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:eastAsia'), font_name_east)
    rFonts.set(qn('w:ascii'), font_name_ascii)
    rFonts.set(qn('w:hAnsi'), font_name_ascii)


def set_paragraph_spacing(paragraph, line_spacing=Pt(20), before=0, after=0, first_line_indent=None):
    """Set paragraph spacing"""
    pf = paragraph.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = line_spacing
    pf.space_before = before
    pf.space_after = after
    if first_line_indent is not None:
        pf.first_line_indent = first_line_indent


def add_heading_text(doc, text, level=1):
    """Add heading with proper formatting"""
    p = doc.add_paragraph()

    if level == 0:  # Document title (大标题)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_paragraph_spacing(p, Pt(20), before=0, after=Pt(30))
        run = p.add_run(text)
        set_run_font(run, '黑体', '黑体', Pt(15), bold=True)
    elif level == 1:  # Chapter (## 第X章)
        set_paragraph_spacing(p, Pt(20), before=0, after=Pt(18))
        run = p.add_run(text)
        set_run_font(run, '黑体', '黑体', Pt(14), bold=True)
    elif level == 2:  # Section (### X.Y)
        set_paragraph_spacing(p, Pt(20), before=0, after=Pt(12))
        run = p.add_run(text)
        set_run_font(run, '黑体', '黑体', Pt(14), bold=True)
    elif level == 3:  # Subsection (#### X.Y.Z)
        set_paragraph_spacing(p, Pt(20), before=0, after=Pt(6))
        run = p.add_run(text)
        set_run_font(run, '黑体', '黑体', Pt(12), bold=True)

    return p


def add_body_text(doc, text, indent=True):
    """Add body paragraph with 宋体 小四"""
    p = doc.add_paragraph()
    set_paragraph_spacing(p, Pt(20), before=0, after=0, first_line_indent=Pt(24) if indent else None)
    run = p.add_run(text)
    set_run_font(run, '宋体', '宋体', Pt(12))
    return p


def parse_md_table(lines):
    """Parse pipe table lines into rows/cols"""
    rows = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('|-'):  # skip separator
            continue
        if line.startswith('|') and line.endswith('|'):
            cells = [c.strip() for c in line.strip('|').split('|')]
            rows.append(cells)
    return rows


def add_table(doc, rows):
    """Add a docx table from parsed rows"""
    if not rows:
        return
    nrows = len(rows)
    ncols = max(len(r) for r in rows)

    table = doc.add_table(rows=nrows, cols=ncols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Style
    table.style = 'Table Grid'

    for ri, row_data in enumerate(rows):
        for ci in range(ncols):
            cell = table.cell(ri, ci)
            cell.text = row_data[ci] if ci < len(row_data) else ''
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    set_run_font(run, '宋体', '宋体', Pt(10.5), bold=(ri == 0))

    return table


def convert_md_to_docx(md_path, docx_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    doc = create_document()
    lines = md_text.split('\n')

    i = 0
    in_code_block = False
    in_table = False
    table_lines = []

    while i < len(lines):
        line = lines[i]

        # Code block
        if line.strip().startswith('```'):
            if in_code_block:
                in_code_block = False
            else:
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            p = doc.add_paragraph()
            set_paragraph_spacing(p, Pt(12), before=0, after=0)
            run = p.add_run(line)
            set_run_font(run, 'Consolas', '仿宋', Pt(9))
            i += 1
            continue

        # Pipe table - collect consecutive table lines
        if line.strip().startswith('|') and line.strip().endswith('|'):
            table_lines.append(line)
            in_table = True
            i += 1
            # Check next line
            continue

        # If we were in a table, flush it
        if in_table:
            rows = parse_md_table(table_lines)
            if rows:
                doc.add_paragraph()  # blank line before
                add_table(doc, rows)
                doc.add_paragraph()  # blank line after
            table_lines = []
            in_table = False
            # Don't skip current line - process it below

        stripped = line.strip()

        # Skip empty lines (handled by table flush above)
        if not stripped:
            i += 1
            continue

        # Headings
        heading_match = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            add_heading_text(doc, text, level)
            i += 1
            continue

        # Image placeholder
        img_match = re.match(r'!\[(.*?)\]\(.*?\)', stripped)
        if img_match:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(f'[图: {img_match.group(1)} - 待插入截图]')
            set_run_font(run, '宋体', '宋体', Pt(10.5))
            i += 1
            continue

        # Formula
        if stripped.startswith('$$') and stripped.endswith('$$'):
            formula = stripped.strip('$')
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(formula)
            set_run_font(run, '宋体', '宋体', Pt(12))
            i += 1
            continue

        # Remove image from text references: ![text](url) → text
        text = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', stripped)
        # Remove regular links: [text](url) → text
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Remove bold markers
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'\*(.*?)\*', r'\1', text)

        if text:
            add_body_text(doc, text)

        i += 1

    doc.save(docx_path)
    print(f"✅ Saved to {docx_path}")
    return doc


if __name__ == '__main__':
    md_path = '/mnt/d/tmp/论文_边缘AI_优化完整版_v2.md'
    docx_path = '/mnt/d/tmp/论文_边缘AI_DOCX.docx'
    convert_md_to_docx(md_path, docx_path)
