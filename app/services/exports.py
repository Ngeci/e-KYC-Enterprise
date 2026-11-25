"""Excel and PDF renderings of a report dict produced by calc.report()."""
import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .calc import fmt

GREEN = "138A4B"


def to_xlsx(report, subtitle):
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"[:31]
    ws["A1"] = report["title"]
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, color="666666")
    header_row = 4
    for i, (label, _) in enumerate(report["columns"], start=1):
        c = ws.cell(row=header_row, column=i, value=label)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=GREEN)
        c.alignment = Alignment(horizontal="center")
    for r, row in enumerate(report["rows"], start=header_row + 1):
        for i, ((_, kind), value) in enumerate(zip(report["columns"], row), start=1):
            cell = ws.cell(row=r, column=i, value=value)
            if kind == "pct":
                cell.number_format = "0.0%"
            elif kind == "int":
                cell.number_format = "#,##0"
            elif kind == "ratio":
                cell.number_format = "0.00"
            elif kind == "growth" and value is not None:
                cell.value = value / 100
                cell.number_format = "+0.0%;-0.0%"
    for i in range(1, len(report["columns"]) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 20
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def to_pdf(report, subtitle):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=report["title"])
    styles = getSampleStyleSheet()
    data = [[label for label, _ in report["columns"]]]
    for row in report["rows"]:
        data.append([fmt(v, kind) for (_, kind), v in zip(report["columns"], row)])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + GREEN)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F4")]),
    ]))
    doc.build([Paragraph(report["title"], styles["Title"]), Paragraph(subtitle, styles["Normal"]), Spacer(1, 12), table,
               Spacer(1, 12), Paragraph(f"Generated {datetime.utcnow():%Y-%m-%d %H:%M} UTC. Figures come from imported "
                                        "reports only; no values are estimated.", styles["Italic"])])
    return buffer.getvalue()
