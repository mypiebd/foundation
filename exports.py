"""CSV and PDF report builders.

Every table in the app can leave as a CSV. The report card is a PDF when
reportlab is installed and a print-ready HTML page otherwise, so the app
still works on a bare PythonAnywhere account.
"""

import csv
import io
from datetime import date

from flask import Response

from models import Attendance, Result, db

try:                                    # optional — see module docstring
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)
    PDF_AVAILABLE = True
except ImportError:                     # pragma: no cover
    PDF_AVAILABLE = False

INK = "#07091C"
RED = "#E2001A"


def csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        buffer.getvalue().encode("utf-8-sig"),   # Excel-friendly
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ------------------------------------------------------------- CSVs --------

def students_csv(students, summaries):
    rows = []
    for s in students:
        a = summaries.get(s.id, {})
        rows.append([s.username, s.full_name, s.phone or "", s.email or "",
                     s.branch or "", s.batch.name if s.batch else "",
                     s.status.title(), a.get("held", 0), a.get("attended", 0),
                     f'{a.get("percent", 0)}%'])
    return csv_response(
        "students.csv",
        ["Student ID", "Name", "Phone", "Email", "Branch", "Batch", "Status",
         "Classes held", "Attended", "Attendance"],
        rows)


def credentials_csv(users):
    rows = [[u.username, u.full_name, u.role.title(),
             u.initial_password or "(changed by user)",
             u.phone or "", u.branch or "",
             u.batch.name if getattr(u, "batch", None) else "",
             u.status.title()] for u in users]
    return csv_response(
        "credentials.csv",
        ["Username", "Name", "Role", "First password", "Phone", "Branch",
         "Batch", "Status"], rows)


def attendance_grid_csv(course, students, start, end):
    """Students down the side, class dates across the top."""
    q = Attendance.query.filter(Attendance.course_id == course.id)
    if start:
        q = q.filter(Attendance.date >= start)
    if end:
        q = q.filter(Attendance.date <= end)
    records = q.all()
    dates = sorted({r.date for r in records})
    index = {(r.student_id, r.date): r.status for r in records}

    header = ["Student ID", "Name"] + [d.strftime("%d %b") for d in dates] + \
             ["Held", "Attended", "Attendance"]
    rows = []
    for s in students:
        marks = [index.get((s.id, d), "") for d in dates]
        held = sum(1 for m in marks if m)
        attended = sum(1 for m in marks if m in ("Present", "Late"))
        pct = round(attended / held * 100, 1) if held else 0
        rows.append([s.username, s.full_name] + [m[:1] if m else "-" for m in marks] +
                    [held, attended, f"{pct}%"])
    return csv_response(f"attendance_{course.course_code}.csv", header, rows)


def marksheet_csv(course, students, assessments):
    results = {}
    if assessments:
        for r in Result.query.filter(
                Result.assessment_id.in_([a.id for a in assessments])).all():
            results[(r.student_id, r.assessment_id)] = r

    header = ["Student ID", "Name"] + \
             [f"{a.title} (/{a.max_score:g})" for a in assessments] + ["Average %"]
    rows = []
    for s in students:
        cells, pcts = [], []
        for a in assessments:
            r = results.get((s.id, a.id))
            if r and r.score is not None:
                cells.append(f"{r.score:g}")
                pcts.append(r.score / a.max_score * 100 if a.max_score else 0)
            else:
                cells.append("")
        avg = f"{round(sum(pcts) / len(pcts), 1)}%" if pcts else ""
        rows.append([s.username, s.full_name] + cells + [avg])
    return csv_response(f"marksheet_{course.course_code}.csv", header, rows)


# ---------------------------------------------------------- report card ----

def report_card_pdf(student, data):
    """data comes from helpers-built context in views_admin.student_profile."""
    if not PDF_AVAILABLE:
        return None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title=f"Report — {student.full_name}",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=17, leading=21,
                        textColor=colors.HexColor(INK), spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9,
                         textColor=colors.HexColor("#5A6072"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11.5, leading=14,
                        textColor=colors.HexColor(INK), spaceBefore=12, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=12)

    story = [Paragraph(data["org_name"], sub),
             Paragraph(f"Student report — {student.full_name}", h1),
             Paragraph(
                 " &nbsp;·&nbsp; ".join(filter(None, [
                     f"ID {student.username}",
                     student.branch,
                     student.batch.name if student.batch else None,
                     student.phone,
                     data["window_label"],
                 ])), sub),
             Spacer(1, 6)]

    def table(header, rows, widths):
        t = Table([header] + rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F2F5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(INK)),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDE1E8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    overall = data["overall"]
    story.append(Paragraph("Attendance", h2))
    att_rows = [[
        r["course"].course_code, r["course"].course_name[:34],
        str(r["held"]), str(r["attended"]), str(r["late"]), str(r["absent"]),
        f'{r["percent"]}%'] for r in data["per_course"]]
    att_rows.append(["", "Overall", str(overall["held"]), str(overall["attended"]),
                     str(overall["late"]), str(overall["absent"]),
                     f'{overall["percent"]}%'])
    story.append(table(["Code", "Course", "Held", "Attended", "Late", "Absent", "Rate"],
                       att_rows,
                       [22 * mm, 55 * mm, 16 * mm, 20 * mm, 14 * mm, 16 * mm, 18 * mm]))

    story.append(Paragraph("Assessment results", h2))
    if data["results"]:
        rows = []
        for r in data["results"]:
            a = r.assessment
            rows.append([a.course.course_code, a.title[:30], a.kind,
                         f"{r.score:g}/{a.max_score:g}" if r.score is not None else "—",
                         f"{r.percent}%" if r.percent is not None else "—",
                         Paragraph((r.feedback or "")[:180], body)])
        story.append(table(["Code", "Assessment", "Type", "Score", "%", "Feedback"], rows,
                           [20 * mm, 38 * mm, 22 * mm, 20 * mm, 14 * mm, 47 * mm]))
        avg = data["average"]
        story.append(Spacer(1, 5))
        story.append(Paragraph(
            f"Average across marked work: <b>{avg}%</b>" if avg is not None
            else "No work has been marked yet.", body))
    else:
        story.append(Paragraph("No assessments recorded in this period.", body))

    if data["outstanding"]:
        story.append(Paragraph("Work not yet submitted", h2))
        story.append(table(
            ["Code", "Assessment", "Due"],
            [[a.course.course_code, a.title[:44],
              a.due_date.strftime("%d %b %Y") if a.due_date else "—"]
             for a in data["outstanding"]],
            [22 * mm, 100 * mm, 39 * mm]))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f"Generated {date.today().strftime('%d %B %Y')} · {data['org_name']}", sub))

    doc.build(story)
    buffer.seek(0)
    return Response(buffer.read(), mimetype="application/pdf", headers={
        "Content-Disposition":
            f"attachment; filename=report_{student.username}.pdf"})
