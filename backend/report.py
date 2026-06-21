# backend/report.py
#
# Builds a per-patient PDF recovery report from the saved session log. Pulls
# every saved session whose patient_id matches (sessions with no patient_id
# form the "unassigned" report), then renders a summary, an NME-over-time
# chart, and a per-session table. Pure reportlab -- no system/native deps.

import io
from datetime import datetime
from typing import Any, Optional

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import storage

ACCENT = colors.HexColor("#14b8a6")
INK = colors.HexColor("#0f1720")
MUTED = colors.HexColor("#5b6b7d")
LINE = colors.HexColor("#d4dde6")
BAD = colors.HexColor("#dc2626")
TREND_ARROW = {"up": "↑ up", "down": "↓ down", "stable": "→ stable"}


def sessions_for_patient(patient_id: Optional[str]) -> list[dict[str, Any]]:
    """All saved sessions for a patient, oldest first.

    `patient_id=None` (or empty) selects sessions recorded without an ID.
    """

    target = patient_id or None
    return [
        s
        for s in storage.load_sessions()
        if (s.get("patient_id") or None) == target
    ]


def _fmt_time(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        # Saved timestamps are UTC (tz-aware, e.g. "...+00:00"). Convert to the
        # server's local time so the report matches the wall clock the session
        # was actually recorded at (the web UI already shows local time).
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def _num(value: Any, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:.{digits}f}"


def _nme_chart(sessions: list[dict[str, Any]]) -> Drawing:
    width, height = 460, 180
    drawing = Drawing(width, height)
    points = [
        (i, s["nme"])
        for i, s in enumerate(sessions)
        if isinstance(s.get("nme"), (int, float))
    ]
    if len(points) < 1:
        drawing.add(String(10, height / 2, "No NME data to plot.", fillColor=MUTED))
        return drawing

    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 36, 28, width - 60, height - 56
    plot.data = [points]
    plot.lines[0].strokeColor = ACCENT
    plot.lines[0].strokeWidth = 2
    plot.lines[0].symbol = makeMarker("FilledCircle")
    plot.lines[0].symbol.fillColor = ACCENT
    plot.lines[0].symbol.size = 5

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    plot.xValueAxis.valueMin = min(xs)
    plot.xValueAxis.valueMax = max(xs) if max(xs) > min(xs) else min(xs) + 1
    plot.xValueAxis.valueStep = 1
    y_lo, y_hi = min(ys), max(ys)
    pad = (y_hi - y_lo) * 0.15 or 0.2
    plot.yValueAxis.valueMin = max(0, y_lo - pad)
    plot.yValueAxis.valueMax = y_hi + pad
    plot.xValueAxis.labelTextFormat = lambda v: f"#{int(v) + 1}"

    drawing.add(plot)
    drawing.add(String(36, height - 16, "NME over sessions", fontSize=11, fillColor=INK))
    return drawing


def build_patient_report(patient_id: Optional[str]) -> Optional[bytes]:
    """Render the PDF for one patient. Returns None if they have no sessions."""

    sessions = sessions_for_patient(patient_id)
    if not sessions:
        return None

    label = patient_id or "Unassigned"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], textColor=INK, fontSize=20, spaceAfter=2
    )
    sub_style = ParagraphStyle(
        "sub", parent=styles["Normal"], textColor=MUTED, fontSize=9, spaceAfter=14
    )
    h2_style = ParagraphStyle(
        "h2", parent=styles["Heading2"], textColor=INK, fontSize=13, spaceBefore=14
    )
    foot_style = ParagraphStyle(
        "foot", parent=styles["Normal"], textColor=MUTED, fontSize=8, leading=11
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Nervify NME Report — {label}",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    latest = sessions[-1]
    target_pct = latest.get("target_percentage")
    flow: list[Any] = [
        Paragraph("Nervify — NME Recovery Report", title_style),
        Paragraph(
            f"Patient <b>{label}</b> &nbsp;·&nbsp; generated "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;·&nbsp; "
            f"target {_num(target_pct, 0)}% MVC",
            sub_style,
        ),
    ]

    # ---- Summary cards ----
    nme_vals = [s["nme"] for s in sessions if isinstance(s.get("nme"), (int, float))]
    summary = [
        ["Latest NME", "Trend", "Sessions", "Date range"],
        [
            _num(latest.get("nme"), 3),
            TREND_ARROW.get(latest.get("trend"), "—"),
            str(len(sessions)),
            f"{_fmt_time(sessions[0].get('timestamp'))}\nto {_fmt_time(latest.get('timestamp'))}",
        ],
    ]
    summary_table = Table(summary, colWidths=[42 * mm] * 4)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4f3")),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, 1), 15),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 1), (-1, 1), INK),
                # The "Date range" value is a two-line date string, not a big
                # number — shrink it so it fits the 42 mm column instead of
                # overflowing at the 15 pt headline size.
                ("FONTSIZE", (3, 1), (3, 1), 8.5),
                ("FONTNAME", (3, 1), (3, 1), "Helvetica"),
                ("LEADING", (3, 1), (3, 1), 11),
                ("TOPPADDING", (0, 1), (-1, 1), 6),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    flow += [summary_table, Spacer(1, 6), _nme_chart(sessions)]

    # ---- Per-session table ----
    flow.append(Paragraph("Sessions", h2_style))
    header = [
        "#",
        "Date",
        "NME",
        "%MVC force",
        "%MVC EMG",
        "Force (N)",
        "EMG RMS",
        "Trend",
        "",
    ]
    rows = [header]
    flagged: list[int] = []
    for i, s in enumerate(sessions):
        if s.get("emg_clipped"):
            flagged.append(i + 1)
        rows.append(
            [
                str(i + 1),
                _fmt_time(s.get("timestamp")),
                _num(s.get("nme"), 3),
                f"{_num(s.get('percent_mvc_force'), 1)}%",
                f"{_num(s.get('percent_mvc_emg'), 1)}%",
                _num(s.get("force_n"), 1),
                _num(s.get("total_emg_rms"), 1),
                TREND_ARROW.get(s.get("trend"), "—"),
                "⚠" if s.get("emg_clipped") else "",
            ]
        )
    table = Table(rows, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (-1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fa")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, s in enumerate(sessions):
        if s.get("emg_clipped"):
            style.append(("TEXTCOLOR", (-1, i + 1), (-1, i + 1), BAD))
    table.setStyle(TableStyle(style))
    flow += [table, Spacer(1, 10)]

    if flagged:
        flow.append(
            Paragraph(
                f"⚠ EMG was clipped (saturated) during session(s) "
                f"{', '.join(map(str, flagged))}; their NME is understated and should "
                "be interpreted with caution.",
                ParagraphStyle("warn", parent=foot_style, textColor=BAD),
            )
        )
        flow.append(Spacer(1, 6))

    # ---- Footnote ----
    flow.append(
        Paragraph(
            "<b>About NME.</b> Neuromuscular Efficiency normalizes force and EMG to "
            "each session's maximum voluntary contraction (MVC), then divides: "
            "NME = %MVC force / %MVC EMG. Higher values mean more force produced per "
            "unit of muscle electrical activity. Because both values are normalized "
            "to the session's own MVC, NME is comparable across sessions and patients. "
            "Generated by Nervify.",
            foot_style,
        )
    )

    doc.build(flow)
    return buffer.getvalue()
