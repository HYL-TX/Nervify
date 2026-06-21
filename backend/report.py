# backend/report.py
#
# Builds a per-patient PDF recovery report from the saved session log. Pulls
# every saved session whose patient_id matches (sessions with no patient_id
# form the "unassigned" report), then renders a branded header/footer, a patient
# information strip, a key-results card, an NME-over-time chart, a per-session
# table, and the clinical interpretation / method / references sections.
#
# Typography: the report uses Aptos (Microsoft) when the font is available on
# the host and falls back to the standard PDF Helvetica family otherwise, so
# generation never fails on a machine without Aptos installed.

import glob
import io
import os
from datetime import datetime
from typing import Any, Optional

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFontFile
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import config, storage

# ---- Palette (modern clinical slate + teal) ----
BRAND = colors.HexColor("#0f766e")   # deep teal — header band, section titles
ACCENT = colors.HexColor("#14b8a6")  # bright teal — NME value, chart line
INK = colors.HexColor("#0f172a")     # slate-900 — primary text
MUTED = colors.HexColor("#64748b")   # slate-500 — secondary text
SLATE = colors.HexColor("#475569")   # slate-600 — reference text
LINE = colors.HexColor("#e2e8f0")    # slate-200 — hairlines
SOFT = colors.HexColor("#f1f5f9")    # slate-100 — card backgrounds
BAD = colors.HexColor("#dc2626")     # red — clipping warnings

TREND_ARROW = {
    "up": "↑ Improving",
    "down": "↓ Declining",
    "stable": "→ Stable",
    "baseline": "— First session",
}

# Cached after first registration so we only touch the filesystem / pdfmetrics
# once per process.
_FONTS: Optional[dict] = None


def _report_fonts() -> dict:
    """Register Aptos if available; fall back to the Helvetica family.

    Aptos ships with Microsoft 365 in a CloudFonts cache whose files have opaque
    numeric names, so faces are discovered by reading each TTF's family/style
    name rather than hard-coding paths. Returns a dict mapping
    normal/bold/italic/boldItalic to registered font names.
    """

    global _FONTS
    if _FONTS is not None:
        return _FONTS

    fonts = {
        "normal": "Helvetica",
        "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique",
        "boldItalic": "Helvetica-BoldOblique",
    }

    local = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
    search_dirs = [
        os.path.join(local, "Microsoft", "FontCache", "4", "CloudFonts", "Aptos"),
        r"C:\Windows\Fonts",
    ]
    found: dict[str, str] = {}
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        # The dedicated Aptos cache folder only holds the plain family; in the
        # shared Windows font dir, glob just the Aptos* files (not all fonts).
        pattern = "*.ttf" if os.path.basename(directory).lower() == "aptos" else "Aptos*.ttf"
        for path in glob.glob(os.path.join(directory, pattern)):
            try:
                face = TTFontFile(path)
                family = (face.familyName or b"").decode("latin-1", "ignore").lower()
                # Keep only the base "Aptos" family (skip Display / Narrow / Mono).
                if family != "aptos":
                    continue
                style = (face.styleName or b"Regular").decode("latin-1", "ignore").lower()
            except Exception:
                continue
            if "bold" in style and "italic" in style:
                found.setdefault("boldItalic", path)
            elif "bold" in style:
                found.setdefault("bold", path)
            elif "italic" in style or "oblique" in style:
                found.setdefault("italic", path)
            else:
                found.setdefault("normal", path)
        if found.get("normal"):
            break

    if found.get("normal"):
        try:
            normal = found["normal"]
            bold = found.get("bold", normal)
            italic = found.get("italic", normal)         # cloud cache has no italic
            bold_italic = found.get("boldItalic", bold)  # -> map to upright/bold
            pdfmetrics.registerFont(TTFont("Aptos", normal))
            pdfmetrics.registerFont(TTFont("Aptos-Bold", bold))
            pdfmetrics.registerFont(TTFont("Aptos-Italic", italic))
            pdfmetrics.registerFont(TTFont("Aptos-BoldItalic", bold_italic))
            pdfmetrics.registerFontFamily(
                "Aptos",
                normal="Aptos",
                bold="Aptos-Bold",
                italic="Aptos-Italic",
                boldItalic="Aptos-BoldItalic",
            )
            fonts = {
                "normal": "Aptos",
                "bold": "Aptos-Bold",
                "italic": "Aptos-Italic",
                "boldItalic": "Aptos-BoldItalic",
            }
        except Exception:
            pass  # keep Helvetica fallback

    _FONTS = fonts
    return fonts


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


def _nme_chart(sessions: list[dict[str, Any]], fonts: dict) -> Drawing:
    width, height = 470, 180
    drawing = Drawing(width, height)
    points = [
        (i, s["nme"])
        for i, s in enumerate(sessions)
        if isinstance(s.get("nme"), (int, float))
    ]
    if len(points) < 1:
        drawing.add(
            String(10, height / 2, "No NME data to plot.", fontName=fonts["normal"], fillColor=MUTED)
        )
        return drawing

    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 40, 30, width - 64, height - 56
    plot.data = [points]
    plot.lines[0].strokeColor = ACCENT
    plot.lines[0].strokeWidth = 2.5
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

    # Light, modern axis styling.
    for axis in (plot.xValueAxis, plot.yValueAxis):
        axis.strokeColor = LINE
        axis.labels.fontName = fonts["normal"]
        axis.labels.fontSize = 8
        axis.labels.fillColor = MUTED
    plot.yValueAxis.visibleGrid = 1
    plot.yValueAxis.gridStrokeColor = LINE
    plot.yValueAxis.gridStrokeWidth = 0.4

    drawing.add(plot)
    drawing.add(
        String(40, height - 14, "NME over sessions", fontName=fonts["bold"], fontSize=11, fillColor=INK)
    )
    return drawing


def build_patient_report(patient_id: Optional[str]) -> Optional[bytes]:
    """Render the PDF for one patient. Returns None if they have no sessions."""

    sessions = sessions_for_patient(patient_id)
    if not sessions:
        return None

    fonts = _report_fonts()
    F, FB = fonts["normal"], fonts["bold"]

    label = patient_id or "Unassigned"
    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    latest = sessions[-1]
    target_pct = latest.get("target_percentage")
    target_str = (
        _num(target_pct, 0)
        if isinstance(target_pct, (int, float))
        else str(config.TARGET_PERCENTAGE)
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], fontName=FB, textColor=INK,
        fontSize=22, leading=25, spaceAfter=1, alignment=0,
    )
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"], fontName=F, textColor=MUTED,
        fontSize=9.5, leading=13,
    )
    h2_style = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontName=FB, textColor=BRAND,
        fontSize=12.5, leading=15, spaceBefore=2, spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "body", parent=styles["Normal"], fontName=F, textColor=INK,
        fontSize=8.7, leading=12.8, alignment=TA_JUSTIFY,
    )
    ref_style = ParagraphStyle(
        "ref", parent=styles["Normal"], fontName=F, textColor=SLATE,
        fontSize=8, leading=11.5, alignment=TA_JUSTIFY,
    )
    warn_style = ParagraphStyle(
        "warn", parent=body_style, textColor=BAD,
    )

    def _section(text: str) -> list[Any]:
        return [
            Paragraph(text, h2_style),
            HRFlowable(width="100%", thickness=0.7, color=LINE, spaceBefore=1, spaceAfter=7),
        ]

    # ---- Page furniture: brand header + footer with page numbers ----
    def _decorate(canvas, _doc) -> None:
        canvas.saveState()
        w, h = A4
        # Top brand bar.
        canvas.setFillColor(BRAND)
        canvas.rect(0, h - 4 * mm, w, 4 * mm, stroke=0, fill=1)
        # Wordmark + running tagline / patient.
        canvas.setFillColor(BRAND)
        canvas.setFont(FB, 12)
        canvas.drawString(18 * mm, h - 11.5 * mm, "Nervify")
        canvas.setFillColor(MUTED)
        canvas.setFont(F, 8)
        canvas.drawString(
            18 * mm + canvas.stringWidth("Nervify", FB, 12) + 5,
            h - 11.5 * mm,
            "Neuromuscular Efficiency Measurement",
        )
        canvas.drawRightString(w - 18 * mm, h - 11.5 * mm, f"Patient: {label}")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, h - 14.5 * mm, w - 18 * mm, h - 14.5 * mm)
        # Footer.
        canvas.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(F, 7.5)
        canvas.drawString(18 * mm, 10 * mm, "Confidential — for clinical use only")
        canvas.drawCentredString(w / 2.0, 10 * mm, f"Generated {gen_date} · Nervify")
        canvas.drawRightString(w - 18 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Nervify NME Report — {label}",
        author="Nervify",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
    )

    flow: list[Any] = [
        Paragraph("NME Recovery Report", title_style),
        Paragraph(
            "Neuromuscular Efficiency assessment of the thumb (abductor pollicis brevis)",
            subtitle_style,
        ),
        Spacer(1, 11),
    ]

    # ---- Patient information strip ----
    info = [
        ["PATIENT", "REPORT DATE", "TARGET LEVEL"],
        [label, gen_date, f"{target_str}% MVC"],
    ]
    info_table = Table(info, colWidths=[58 * mm] * 3)
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FB),
                ("FONTSIZE", (0, 0), (-1, 0), 7),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONTNAME", (0, 1), (-1, 1), FB),
                ("FONTSIZE", (0, 1), (-1, 1), 10.5),
                ("TEXTCOLOR", (0, 1), (-1, 1), INK),
                ("LINEABOVE", (0, 0), (-1, 0), 0.7, LINE),
                ("LINEBELOW", (0, 1), (-1, 1), 0.7, LINE),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
            ]
        )
    )
    flow += [info_table, Spacer(1, 12)]

    # ---- Key results card ----
    progress = (
        "— First session"
        if len(sessions) == 1
        else TREND_ARROW.get(latest.get("trend"), "—")
    )
    summary = [
        ["LATEST NME", "PROGRESS", "SESSIONS", "DATE RANGE"],
        [
            _num(latest.get("nme"), 3),
            progress,
            str(len(sessions)),
            f"{_fmt_time(sessions[0].get('timestamp'))}\nto {_fmt_time(latest.get('timestamp'))}",
        ],
    ]
    summary_table = Table(summary, colWidths=[43.5 * mm] * 4)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("FONTNAME", (0, 0), (-1, 0), FB),
                ("FONTSIZE", (0, 0), (-1, 0), 7),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                # Value row defaults.
                ("FONTNAME", (0, 1), (-1, 1), FB),
                ("FONTSIZE", (0, 1), (-1, 1), 14),
                ("TEXTCOLOR", (0, 1), (-1, 1), INK),
                # NME headline value in accent.
                ("FONTSIZE", (0, 1), (0, 1), 19),
                ("TEXTCOLOR", (0, 1), (0, 1), ACCENT),
                # Progress is a text label — shrink so it fits its column.
                ("FONTSIZE", (1, 1), (1, 1), 10.5),
                # Date range is a two-line date string.
                ("FONTNAME", (3, 1), (3, 1), F),
                ("FONTSIZE", (3, 1), (3, 1), 8.5),
                ("LEADING", (3, 1), (3, 1), 11),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("LINEAFTER", (0, 0), (-2, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    flow += [summary_table, Spacer(1, 10), _nme_chart(sessions, fonts), Spacer(1, 6)]

    # ---- Per-session table ----
    flow += _section("Sessions")
    header = [
        "Session",
        "Date",
        "NME\n(higher = better)",
        "%MVC force",
        "%MVC EMG",
        "Force (N)",
        "EMG RMS",
        "Progress",
        "",
    ]
    rows = [header]
    flagged: list[int] = []
    for i, s in enumerate(sessions):
        if s.get("emg_clipped"):
            flagged.append(i + 1)
        rows.append(
            [
                f"Session {i + 1}",
                _fmt_time(s.get("timestamp")),
                _num(s.get("nme"), 3),
                f"{_num(s.get('percent_mvc_force'), 1)}%",
                f"{_num(s.get('percent_mvc_emg'), 1)}%",
                _num(s.get("force_n"), 1),
                _num(s.get("total_emg_rms"), 1),
                # The first session is always the baseline (no prior to compare),
                # even if older saved data stored its trend as "stable".
                "— First session" if i == 0 else TREND_ARROW.get(s.get("trend"), "—"),
                "!" if s.get("emg_clipped") else "",
            ]
        )
    table = Table(rows, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), F),
        ("FONTNAME", (0, 0), (-1, 0), FB),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (-1, 0), (-1, -1), "CENTER"),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SOFT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i, s in enumerate(sessions):
        if s.get("emg_clipped"):
            style.append(("TEXTCOLOR", (-1, i + 1), (-1, i + 1), BAD))
    table.setStyle(TableStyle(style))
    flow += [table, Spacer(1, 8)]

    if flagged:
        flow.append(
            Paragraph(
                f"<b>Caution (!).</b> EMG was clipped (saturated) during session(s) "
                f"{', '.join(map(str, flagged))}; their NME is understated and should "
                "be interpreted with caution.",
                warn_style,
            )
        )
        flow.append(Spacer(1, 8))

    # ---- Clinical interpretation ----
    flow += _section("Clinical Interpretation")
    flow.append(
        Paragraph(
            "<b>What NME measures.</b> Neuromuscular Efficiency (NME) = %MVC force ÷ %MVC EMG. "
            "Both force and EMG are normalised to the patient's own maximum voluntary contraction "
            "(MVC) recorded at the start of each session, so the ratio is comparable across "
            "sessions regardless of day-to-day variation in absolute strength. "
            "<b>A higher NME means the muscle produces more force for every unit of electrical "
            "activity — indicating better neuromuscular efficiency.</b>",
            body_style,
        )
    )
    flow.append(Spacer(1, 5))
    flow.append(
        Paragraph(
            "<b>How to read progress.</b> 'Improving' means this session's NME is more than 5% "
            "higher than the previous session; 'Declining' means more than 5% lower; 'Stable' "
            "means within 5% in either direction. Progress is always relative to this patient's "
            "own prior session — not a fixed population standard.",
            body_style,
        )
    )
    flow.append(Spacer(1, 5))
    flow.append(
        Paragraph(
            "<b>On discharge and normal range.</b> No population-wide normative threshold has "
            "been established for thenar (APB) NME. Unlike conditions requiring lifelong "
            "training, muscle rehabilitation has a natural endpoint: once the patient's NME "
            "returns to a stable plateau — ideally symmetric with the unaffected hand or "
            "matching a pre-injury baseline — continued device use may no longer be necessary. "
            "The treating clinician should make this determination based on the NME trend across "
            "multiple sessions, functional outcomes, and the specific rehabilitation protocol "
            "in use. Reference values for this patient population should be established through "
            "prospective trial data.",
            body_style,
        )
    )
    flow.append(Spacer(1, 12))

    # ---- Measurement method ----
    tol_pct = int(round(config.TARGET_TOLERANCE * 100))
    flow += _section("Measurement Method")
    flow.append(
        Paragraph(
            f"<b>1. MVC calibration.</b> At the start of each session the patient performs "
            f"{config.MVC_ATTEMPTS_REQUIRED} maximal voluntary contractions (MVC) of the thumb "
            f"(abductor pollicis brevis), each held up to {_num(config.MVC_MAX_SECONDS, 0)} s "
            f"(minimum {_num(config.CONTRACTION_SECONDS, 0)} s), with an enforced "
            f"{_num(config.MVC_REST_SECONDS, 0)} s rest between attempts to limit fatigue. The "
            "highest force and the highest EMG recorded across the attempts define this session's "
            "reference values, <b>MVC force</b> and <b>MVC EMG</b>. Every subsequent value is "
            "expressed as a percentage of these, which is what makes sessions comparable.",
            body_style,
        )
    )
    flow.append(Spacer(1, 5))
    flow.append(
        Paragraph(
            f"<b>2. Submaximal target contraction ({target_str}% MVC).</b> The target force is set "
            f"to {target_str}% of MVC force. The patient gently contracts to hold the force within "
            f"±{tol_pct}% of that target for {_num(config.CONTRACTION_SECONDS, 0)} continuous "
            "seconds; the trial completes automatically once the hold is stable. A controlled "
            "submaximal contraction (rather than another maximal effort) is used because efficiency "
            "is most relevant, and most reliably measured, at the effort levels used in daily function.",
            body_style,
        )
    )
    flow.append(Spacer(1, 5))
    flow.append(
        Paragraph(
            f"<b>3. Signal processing.</b> Force is low-pass filtered at "
            f"{_num(config.FORCE_LOW_PASS_CUTOFF_HZ, 0)} Hz to remove tremor and noise. EMG has a "
            f"{_num(config.NOTCH_FREQUENCY_HZ, 0)} Hz notch filter applied to reject mains "
            "interference, its resting baseline subtracted, and its root-mean-square (RMS) amplitude "
            f"computed over {config.EMG_WINDOW_SECONDS:g}-second windows. The mean force and mean EMG "
            "RMS over the held contraction become the trial's Force (N) and EMG RMS.",
            body_style,
        )
    )
    flow.append(Spacer(1, 5))
    flow.append(
        Paragraph(
            "<b>4. NME computation.</b> %MVC force = trial force ÷ MVC force × 100; "
            "%MVC EMG = trial EMG RMS ÷ MVC EMG × 100; "
            "<b>NME = %MVC force ÷ %MVC EMG</b>. Intuitively, NME asks how much of the patient's "
            "available force capacity they achieved relative to how much of their muscle's electrical "
            "capacity it cost — a higher ratio means the same task is performed more efficiently.",
            body_style,
        )
    )
    flow.append(Spacer(1, 12))

    # ---- References ----
    flow += _section("References")
    flow.append(
        Paragraph(
            "<b>Primary reference.</b> Rainoldi A, Gazzoni M, Casale R. Surface EMG signal "
            "alterations in Carpal Tunnel syndrome: a pilot study. <i>Eur J Appl Physiol</i>. "
            "2008;103(2):233&ndash;242. doi:10.1007/s00421-008-0694-x &mdash; the basis for this "
            "device: patients with carpal tunnel syndrome showed lower neuromuscular efficiency in "
            "the flexor and abductor pollicis brevis at submaximal contraction (10&ndash;30% MVC).",
            ref_style,
        )
    )
    flow.append(Spacer(1, 4))
    ref_items = [
        "Bonfiglioli R, Botter A, Calabrese M, Mussoni P, Violante FS, Merletti R. Surface "
        "electromyography features in manual workers affected by carpal tunnel syndrome. "
        "<i>Muscle Nerve</i>. 2012;45(6):873&ndash;882. doi:10.1002/mus.23258 "
        "(reports NME of the abductor pollicis brevis at 20% and 50% MVC).",
        "Arabadzhiev TI, Dimitrov VG, Dimitrova NA, Dimitrov GV. Interpretation of EMG integral "
        "or RMS and estimates of &lsquo;neuromuscular efficiency&rsquo; can be misleading in "
        "fatiguing contraction. <i>J Electromyogr Kinesiol</i>. 2010;20(2):223&ndash;232. "
        "doi:10.1016/j.jelekin.2009.01.008.",
        "Lawrence JH, De Luca CJ. Myoelectric signal versus force relationship in different human "
        "muscles. <i>J Appl Physiol</i>. 1983;54(6):1653&ndash;1659.",
        "De Luca CJ. The use of surface electromyography in biomechanics. <i>J Appl Biomech</i>. "
        "1997;13(2):135&ndash;163.",
        "Hermens HJ, Freriks B, Disselhorst-Klug C, Rau G. Development of recommendations for SEMG "
        "sensors and sensor placement procedures (SENIAM). <i>J Electromyogr Kinesiol</i>. "
        "2000;10(5):361&ndash;374.",
        "Merletti R, Parker PA. <i>Electromyography: Physiology, Engineering, and Noninvasive "
        "Applications.</i> Hoboken, NJ: Wiley-IEEE Press; 2004.",
    ]
    for i, ref in enumerate(ref_items, start=1):
        flow.append(Paragraph(f"{i}. {ref}", ref_style))
        flow.append(Spacer(1, 2))

    doc.build(flow, onFirstPage=_decorate, onLaterPages=_decorate)
    return buffer.getvalue()
