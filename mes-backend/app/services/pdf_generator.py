"""PDF report generator for worktime and line balance analysis.

Uses reportlab to generate PDF files with tables, charts, and
formatted analysis data.

Dependencies: reportlab
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from html import escape as html_escape
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# reportlab imports (lazy to avoid import errors if not installed)
_RL_AVAILABLE = False
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, HRFlowable,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    _RL_AVAILABLE = True
except ImportError:
    logger.warning(
        "reportlab not installed. PDF generation disabled. "
        "Install with: pip install reportlab"
    )

# PDF color palette
_COLOR_PRIMARY = colors.HexColor("#2563EB")
_COLOR_SECONDARY = colors.HexColor("#64748B")
_COLOR_SUCCESS = colors.HexColor("#16A34A")
_COLOR_WARNING = colors.HexColor("#D97706")
_COLOR_DANGER = colors.HexColor("#DC2626")
_COLOR_BG = colors.HexColor("#F8FAFC")
_COLOR_HEADER_BG = colors.HexColor("#1E3A5F")


def _safe_str(value: Any) -> str:
    """Convert a value to string, escaping HTML/XML special characters."""
    return html_escape(str(value), quote=True)


def _build_styles() -> Dict[str, Any]:
    """Build paragraph styles for the PDF."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="CNTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=28,
        alignment=TA_CENTER,
        textColor=_COLOR_HEADER_BG,
        spaceAfter=6 * mm,
    ))
    styles.add(ParagraphStyle(
        name="CNSubtitle",
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        alignment=TA_CENTER,
        textColor=_COLOR_SECONDARY,
        spaceAfter=10 * mm,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeader",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=20,
        textColor=_COLOR_PRIMARY,
        spaceBefore=8 * mm,
        spaceAfter=4 * mm,
    ))
    styles.add(ParagraphStyle(
        name="BodyCN",
        fontName="Helvetica",
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#334155"),
        spaceAfter=3 * mm,
    ))
    styles.add(ParagraphStyle(
        name="KPIValue",
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
        textColor=_COLOR_PRIMARY,
    ))
    styles.add(ParagraphStyle(
        name="KPILabel",
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=_COLOR_SECONDARY,
    ))
    styles.add(ParagraphStyle(
        name="FooterNote",
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=_COLOR_SECONDARY,
        spaceBefore=10 * mm,
    ))

    return styles


def _make_kpi_table(
    kpi_data: Dict[str, Any],
) -> Table:
    """Create a KPI summary table."""
    styles = _build_styles()

    # Build KPI cells
    header_row = []
    value_row = []
    for label, value in kpi_data.items():
        header_row.append(Paragraph(_safe_str(label), styles["KPILabel"]))
        value_row.append(Paragraph(_safe_str(value), styles["KPIValue"]))

    data = [header_row, value_row]
    col_count = len(kpi_data)

    table = Table(
        data,
        colWidths=[A4[0] / col_count] * col_count,
        rowHeights=[12 * mm, 18 * mm],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _COLOR_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    return table


def _make_data_table(
    headers: List[str],
    rows: List[List[str]],
    col_widths: Optional[List[float]] = None,
) -> Table:
    """Create a styled data table."""
    data = [headers] + rows

    if col_widths is None:
        available = A4[0] - 20 * mm
        col_widths = [available / len(headers)] * len(headers)

    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), _COLOR_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _COLOR_BG]),
    ]
    table.setStyle(TableStyle(style_cmds))
    return table


def generate_worktime_pdf(data: Dict[str, Any]) -> bytes:
    """Generate a worktime analysis PDF report.

    Args:
        data: Dict containing worktime analysis data:
            - station_id: station name
            - period: analysis period
            - kpi: dict of KPI labels and values
            - therblig_stats: list of {symbol, name, count, total_mod, total_seconds, is_waste}
            - operations: list of {action, count, avg_duration_ms, total_duration_ms}
            - efficiency_ranking: list of {action, efficiency}

    Returns:
        PDF file as bytes.
    """
    if not _RL_AVAILABLE:
        raise RuntimeError("reportlab is not installed")

    buf = io.BytesIO()
    styles = _build_styles()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    elements: list = []

    # Title
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    station_id = _safe_str(data.get("station_id", "N/A"))
    period = _safe_str(data.get("period", "N/A"))

    elements.append(Paragraph(
        f"Worktime Analysis Report",
        styles["CNTitle"],
    ))
    elements.append(Paragraph(
        f"Station: {station_id} | Period: {period} | Generated: {now_str}",
        styles["CNSubtitle"],
    ))

    # KPI Summary
    elements.append(Paragraph("Key Performance Indicators", styles["SectionHeader"]))
    kpi_data = data.get("kpi", {})
    if kpi_data:
        elements.append(_make_kpi_table(kpi_data))
    else:
        elements.append(Paragraph("No KPI data available.", styles["BodyCN"]))

    # Therblig Distribution
    elements.append(Paragraph("Therblig (Motion Element) Distribution", styles["SectionHeader"]))
    therblig_stats = data.get("therblig_stats", [])
    if therblig_stats:
        headers = ["Symbol", "Name", "Count", "Total MOD", "Total (s)", "Waste"]
        rows = []
        for t in therblig_stats:
            waste_flag = "Yes" if t.get("is_waste") else ""
            rows.append([
                _safe_str(t.get("symbol", "")),
                _safe_str(t.get("name", "")),
                str(t.get("count", 0)),
                f"{t.get('total_mod', 0):.1f}",
                f"{t.get('total_seconds', 0):.2f}",
                waste_flag,
            ])
        elements.append(_make_data_table(headers, rows))
    else:
        elements.append(Paragraph("No therblig data available.", styles["BodyCN"]))

    # Operations Summary
    elements.append(Paragraph("Operations Summary", styles["SectionHeader"]))
    operations = data.get("operations", [])
    if operations:
        headers = ["Action", "Count", "Avg Duration (ms)", "Total Duration (ms)"]
        rows = []
        for op in operations:
            rows.append([
                _safe_str(op.get("action", "")),
                str(op.get("count", 0)),
                f"{op.get('avg_duration_ms', 0):.0f}",
                f"{op.get('total_duration_ms', 0):.0f}",
            ])
        elements.append(_make_data_table(headers, rows))
    else:
        elements.append(Paragraph("No operations data available.", styles["BodyCN"]))

    # Efficiency Ranking
    elements.append(Paragraph("Station Efficiency Ranking", styles["SectionHeader"]))
    ranking = data.get("efficiency_ranking", [])
    if ranking:
        headers = ["Rank", "Station", "Efficiency", "Status"]
        rows = []
        for i, r in enumerate(ranking, 1):
            eff = r.get("efficiency", 0)
            if eff >= 0.85:
                status = "Normal"
            elif eff >= 0.7:
                status = "Warning"
            else:
                status = "Bottleneck"
            rows.append([str(i), _safe_str(r.get("station", "")), f"{eff:.1%}", status])
        elements.append(_make_data_table(headers, rows))
    else:
        elements.append(Paragraph("No efficiency ranking data available.", styles["BodyCN"]))

    # Footer
    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=_COLOR_SECONDARY))
    elements.append(Paragraph(
        "Edge MES Worktime Analysis System - Auto-generated report. "
        "MOD time standard: 1 MOD = 0.129 seconds.",
        styles["FooterNote"],
    ))

    doc.build(elements)
    return buf.getvalue()


def generate_line_balance_pdf(data: Dict[str, Any]) -> bytes:
    """Generate a line balance analysis PDF report.

    Args:
        data: Dict containing line balance data:
            - line_id: production line name
            - balance_rate: float
            - smoothness_index: float
            - stations: list of {name, cycle_time, load, action, status}
            - bottleneck: dict with bottleneck info
            - ecrs_suggestions: list of {type, description, priority}

    Returns:
        PDF file as bytes.
    """
    if not _RL_AVAILABLE:
        raise RuntimeError("reportlab is not installed")

    buf = io.BytesIO()
    styles = _build_styles()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    elements: list = []

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line_id = _safe_str(data.get("line_id", "N/A"))

    elements.append(Paragraph(
        "Line Balance Analysis Report",
        styles["CNTitle"],
    ))
    elements.append(Paragraph(
        f"Line: {line_id} | Generated: {now_str}",
        styles["CNSubtitle"],
    ))

    # KPI
    elements.append(Paragraph("Key Metrics", styles["SectionHeader"]))
    balance_rate = data.get("balance_rate", 0)
    smoothness = data.get("smoothness_index", 0)
    station_count = len(data.get("stations", []))
    kpi_data = {
        "Balance Rate": f"{balance_rate:.1%}",
        "Smoothness": f"{smoothness:.2f}",
        "Stations": str(station_count),
    }
    elements.append(_make_kpi_table(kpi_data))

    # Station Workload Table
    elements.append(Paragraph("Station Workload Distribution", styles["SectionHeader"]))
    stations = data.get("stations", [])
    if stations:
        headers = ["Station", "Cycle Time (s)", "Load", "Status"]
        rows = []
        for s in stations:
            status = s.get("status", "normal")
            load = s.get("load", 0)
            rows.append([
                _safe_str(s.get("name", "")),
                f"{s.get('cycle_time', 0):.2f}",
                f"{load:.1%}",
                status,
            ])
        elements.append(_make_data_table(headers, rows))
    else:
        elements.append(Paragraph("No station data available.", styles["BodyCN"]))

    # Bottleneck Info
    bottleneck = data.get("bottleneck", {})
    if bottleneck:
        elements.append(Paragraph("Bottleneck Analysis", styles["SectionHeader"]))
        elements.append(Paragraph(
            f"Bottleneck Station: {bottleneck.get('station', 'N/A')} | "
            f"Cycle Time: {bottleneck.get('cycle_time', 0):.2f}s | "
            f"Deviation: {bottleneck.get('deviation', 0):.1%}",
            styles["BodyCN"],
        ))

    # ECRS Suggestions
    ecrs = data.get("ecrs_suggestions", [])
    if ecrs:
        elements.append(Paragraph("ECRS Improvement Suggestions", styles["SectionHeader"]))
        headers = ["Priority", "Type", "Description"]
        rows = []
        for s in ecrs:
            rows.append([
                _safe_str(s.get("priority", "")),
                _safe_str(s.get("type", "")),
                _safe_str(s.get("description", "")),
            ])
        elements.append(_make_data_table(headers, rows))

    # Footer
    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=_COLOR_SECONDARY))
    elements.append(Paragraph(
        "Edge MES Line Balance System - Auto-generated report. "
        "ECRS: Eliminate, Combine, Rearrange, Simplify.",
        styles["FooterNote"],
    ))

    doc.build(elements)
    return buf.getvalue()
