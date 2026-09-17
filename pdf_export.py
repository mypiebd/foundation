"""
PDF generation for class schedules. Uses fpdf2 — pure Python, no compiled
dependencies, so it installs cleanly on the PythonAnywhere free tier.

If fpdf2 is missing the routes fall back to a print-ready HTML page, so the
system never breaks over a PDF.
"""
from collections import defaultdict
from datetime import date

try:
    from fpdf import FPDF
    HAVE_FPDF = True
except ImportError:
    HAVE_FPDF = False

NAVY = (7, 9, 28)
RED  = (226, 0, 26)
GREY = (90, 96, 118)
RULE = (216, 220, 228)
WASH = (244, 245, 248)


# The built-in PDF fonts are latin-1 only, so fold the typographic
# characters that turn up in the Excel sheet down to plain ASCII.
_SUBS = {
    "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2026": "...", "\u00a0": " ", "\u2022": "-",
    "\u00d7": "x", "\u2192": "->", "\u2190": "<-",
}


def clean(s):
    """Make any string safe for the core PDF fonts."""
    if s is None:
        return ""
    s = str(s)
    for bad, good in _SUBS.items():
        s = s.replace(bad, good)
    return s.encode("latin-1", "replace").decode("latin-1")


def ampm(t):
    return t.strftime("%I:%M %p").lstrip("0")


class SchedulePDF(FPDF if HAVE_FPDF else object):
    def __init__(self, title, subtitle, orientation="L"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.doc_title = clean(title)
        self.doc_sub   = clean(subtitle)
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(12, 12, 12)

    def header(self):
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 20, "F")
        self.set_fill_color(*RED)
        self.rect(0, 20, self.w, 1.2, "F")

        self.set_xy(12, 5)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(255, 255, 255)
        self.cell(0, 6, "PIE", ln=0)
        self.set_x(12 + self.get_string_width("PIE") + 2)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(190, 195, 210)
        self.cell(0, 6, "INTERNATIONAL EDUCATION", ln=1)

        half = (self.w - 24) / 2
        self.set_xy(12, 11.5)
        self.set_font("Helvetica", "B", 10.5)
        self.set_text_color(255, 255, 255)
        self.cell(half, 5, self.doc_title, ln=0)

        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(170, 176, 195)
        self.cell(half, 5, self.doc_sub, align="R", ln=1)

        self.set_y(27)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-13)
        self.set_draw_color(*RULE)
        self.line(12, self.get_y(), self.w - 12, self.get_y())
        self.set_y(-10)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*GREY)
        half = (self.w - 24) / 2
        self.cell(half, 5, f"Generated {date.today().strftime('%d %B %Y')}", ln=0)
        self.cell(half, 5, f"Page {self.page_no()} of {{nb}}", align="R", ln=1)

    # ── building blocks ────────────────────────────────────────────────
    def section(self, text):
        if self.get_y() > self.h - 40:
            self.add_page()
        self.ln(2)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*NAVY)
        self.cell(0, 6, clean(text), ln=1)
        self.set_draw_color(*NAVY)
        self.set_line_width(0.4)
        self.line(12, self.get_y(), self.w - 12, self.get_y())
        self.set_line_width(0.2)
        self.ln(1.5)

    def table(self, headers, widths, rows, aligns=None):
        aligns = aligns or ["L"] * len(headers)
        self.set_font("Helvetica", "B", 7.5)
        self.set_fill_color(*WASH)
        self.set_text_color(*GREY)
        self.set_draw_color(*RULE)
        for h, w, a in zip(headers, widths, aligns):
            self.cell(w, 6.5, clean(h).upper(), border="B", align=a, fill=True)
        self.ln()

        self.set_font("Helvetica", "", 8)
        self.set_text_color(20, 22, 40)
        for i, row in enumerate(rows):
            if self.get_y() > self.h - 26:
                self.add_page()
                self.set_font("Helvetica", "B", 7.5)
                self.set_fill_color(*WASH)
                self.set_text_color(*GREY)
                for h, w, a in zip(headers, widths, aligns):
                    self.cell(w, 6.5, clean(h).upper(), border="B", align=a, fill=True)
                self.ln()
                self.set_font("Helvetica", "", 8)
                self.set_text_color(20, 22, 40)
            fill = i % 2 == 1
            self.set_fill_color(250, 250, 252)
            for cell, w, a in zip(row, widths, aligns):
                txt = clean(cell)
                while self.get_string_width(txt) > w - 2 and len(txt) > 3:
                    txt = txt[:-2]
                self.cell(w, 5.6, txt, border="B", align=a, fill=fill)
            self.ln()
        self.ln(1)


def _guard():
    if not HAVE_FPDF:
        raise RuntimeError("fpdf2 not installed")


# ── 1. Weekly schedule, one block per day ──────────────────────────────
def weekly_schedule_pdf(schedules, start, end, who=None):
    _guard()
    sub = f"{start.strftime('%d %b')} to {end.strftime('%d %b %Y')}"
    if who:
        sub = f"{who}   |   {sub}"
    pdf = SchedulePDF("Class Schedule", sub)
    pdf.alias_nb_pages()
    pdf.add_page()

    if not schedules:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*GREY)
        pdf.cell(0, 10, "No classes scheduled in this period.", ln=1)
        return bytes(pdf.output())

    by_day = defaultdict(list)
    for s in schedules:
        by_day[s.date].append(s)

    W = [26, 26, 68, 42, 46, 30, 27]
    H = ["Start", "End", "Class", "Teacher", "Student / group", "Venue", "Status"]
    A = ["L", "L", "L", "L", "L", "L", "L"]

    for day in sorted(by_day):
        items = sorted(by_day[day], key=lambda x: x.start_time)
        teaching = [i for i in items if i.class_type not in ("Break", "Other")]
        pdf.section(f"{day.strftime('%A %d %B %Y')}    -    "
                    f"{len(teaching)} class(es)")
        rows = []
        for s in items:
            rows.append([
                ampm(s.start_time), ampm(s.end_time),
                s.task or "-",
                s.teacher.full_name if s.teacher else "-",
                s.student.full_name if s.student else
                    ("Batch" if s.class_type == "Batch" else "-"),
                s.venue or "-", s.status,
            ])
        pdf.table(H, W, rows, A)
    return bytes(pdf.output())


# ── 2. Batch timetable, grouped by class ───────────────────────────────
def batch_timetable_pdf(schedules):
    _guard()
    pdf = SchedulePDF("Batch Class Timetable", "All fixed batch classes")
    pdf.alias_nb_pages()
    pdf.add_page()

    groups = defaultdict(list)
    for s in schedules:
        groups[(s.task, s.teacher.full_name if s.teacher else "-",
                s.start_time, s.end_time)].append(s)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 5, f"{len(groups)} distinct batch slots   |   "
                   f"{len(schedules)} sessions in total", ln=1)
    pdf.ln(1)

    W = [72, 40, 44, 52, 30, 27]
    H = ["Batch class", "Teacher", "Time", "Days", "Sessions", "Duration"]
    order = {"Sat": 0, "Sun": 1, "Mon": 2, "Tue": 3, "Wed": 4, "Thu": 5, "Fri": 6}

    rows = []
    for (task, teach, st, en), v in sorted(
            groups.items(), key=lambda x: (x[0][2], x[0][0])):
        days = sorted({s.date.strftime("%a") for s in v},
                      key=lambda d: order.get(d, 9))
        mins = (en.hour * 60 + en.minute) - (st.hour * 60 + st.minute)
        rows.append([task, teach, f"{ampm(st)} - {ampm(en)}",
                     ", ".join(days), len(v), f"{mins} min"])
    pdf.section("Every batch class")
    pdf.table(H, W, rows, ["L", "L", "L", "L", "C", "L"])
    return bytes(pdf.output())


# ── 3. One teacher's personal timetable ────────────────────────────────
def teacher_schedule_pdf(teacher, schedules, start, end):
    _guard()
    pdf = SchedulePDF("Teacher Timetable",
                      f"{start.strftime('%d %b')} to {end.strftime('%d %b %Y')}")
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 7, clean(teacher.full_name), ln=1)
    if teacher.subjects:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*GREY)
        pdf.cell(0, 5, clean(teacher.subjects), ln=1)

    teaching = [s for s in schedules
                if s.class_type not in ("Break", "Other") and s.status != "Cancelled"]
    hrs = sum(s.duration_mins or 0 for s in teaching) / 60
    days_on = sorted({s.date.strftime("%a") for s in teaching},
                     key=lambda d: {"Sat":0,"Sun":1,"Mon":2,"Tue":3,
                                    "Wed":4,"Thu":5,"Fri":6}.get(d, 9))
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 5, f"{len(teaching)} classes   |   {hrs:.1f} teaching hours   |   "
                   f"works {', '.join(days_on) if days_on else 'no days'}", ln=1)

    by_day = defaultdict(list)
    for s in schedules:
        by_day[s.date].append(s)

    W = [26, 26, 78, 58, 32, 27]
    H = ["Start", "End", "Class", "Student / group", "Room", "Status"]
    for day in sorted(by_day):
        items = sorted(by_day[day], key=lambda x: x.start_time)
        pdf.section(day.strftime("%A %d %B %Y"))
        rows = [[ampm(s.start_time), ampm(s.end_time), s.task or "-",
                 s.student.full_name if s.student else
                    ("Batch" if s.class_type == "Batch" else "-"),
                 s.room_label, s.status] for s in items]
        pdf.table(H, W, rows)
    return bytes(pdf.output())


# ── 4. A student's own routine, laid out as a weekly grid ──────────────
def student_routine_pdf(student, schedules, start, end, note=None,
                        courses=None, results=None):
    """
    The sheet a student takes home: their week set out day by day, with the
    subject, the teacher and where to be.
    """
    _guard()
    pdf = SchedulePDF("Class Routine",
                      f"{start.strftime('%d %b')} to {end.strftime('%d %b %Y')}",
                      orientation="P")
    pdf.alias_nb_pages()
    pdf.add_page()
    _student_block(pdf, student, schedules, start, end, note, courses, results)
    return bytes(pdf.output())


def students_routines_pdf(items, start, end, note=None):
    """items is a list of (student, schedules) or (student, schedules, courses, results)."""
    """
    Several students in one file, a fresh page each — print once, hand out
    to a whole batch.
    """
    _guard()
    pdf = SchedulePDF("Class Routines",
                      f"{start.strftime('%d %b')} to {end.strftime('%d %b %Y')}",
                      orientation="P")
    pdf.alias_nb_pages()
    for row in items:
        student, schedules = row[0], row[1]
        courses = row[2] if len(row) > 2 else None
        results = row[3] if len(row) > 3 else None
        pdf.add_page()
        _student_block(pdf, student, schedules, start, end, note, courses, results)
    if not items:
        pdf.add_page()
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 10, "No students matched.", ln=1)
    return bytes(pdf.output())


def _student_block(pdf, student, schedules, start, end, note=None,
                   courses=None, results=None):
    """
    A routine card: who it is, the weekly pattern, then the dates.
    Classes only — no marks, no assessment tables. Days with nothing are
    left out entirely.
    """
    from collections import defaultdict

    live = [s for s in schedules if s.status != "Cancelled"]

    # ── Name plate ────────────────────────────────────────────────────
    pdf.set_fill_color(247, 247, 248)
    y0 = pdf.get_y()
    pdf.rect(12, y0, pdf.w - 24, 17, "F")
    pdf.set_xy(15, y0 + 2.5)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 6.5, clean(student.full_name), ln=1)

    bits = [f"ID {student.username}"]
    if getattr(student, "batch", None):
        bits.append(clean(student.batch.name))
    if student.branch:
        bits.append(clean(student.branch))
    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 5, "   ".join(bits), ln=1)
    pdf.set_y(y0 + 20)

    if not live:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*GREY)
        pdf.cell(0, 8, "No classes scheduled in this period.", ln=1)
        return

    # ── The weekly pattern, skipping empty days ───────────────────────
    pattern = defaultdict(list)
    for s in live:
        key = (s.date.weekday(), s.start_time, s.end_time,
               s.task or "", s.teacher.full_name if s.teacher else "",
               s.room_label)
        pattern[key].append(s.date)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]
    order = [5, 6, 0, 1, 2, 3, 4]

    pdf.section("Weekly routine")
    rows = []
    for wd in order:
        items = sorted([k for k in pattern if k[0] == wd], key=lambda k: k[1])
        for i, k in enumerate(items):
            _, st, en, task, teacher, venue = k
            rows.append([day_names[wd] if i == 0 else "",
                         f"{ampm(st)} - {ampm(en)}", task, teacher, venue])
    pdf.table(["Day", "Time", "Class", "Teacher", "Where"],
              [30, 36, 60, 34, 26], rows)

    # ── Every date, grouped by month ──────────────────────────────────
    by_month = defaultdict(list)
    for s in live:
        by_month[(s.date.year, s.date.month)].append(s)

    for (yr, mo) in sorted(by_month):
        items = sorted(by_month[(yr, mo)], key=lambda s: (s.date, s.start_time))
        pdf.section(items[0].date.strftime("%B %Y")
                    + f"    -    {len(items)} class(es)")
        rows = []
        seen = None
        for s in items:
            first = s.date != seen
            seen = s.date
            rows.append([
                s.date.strftime("%d %b") if first else "",
                s.date.strftime("%a") if first else "",
                f"{ampm(s.start_time)} - {ampm(s.end_time)}",
                s.task or "-",
                s.teacher.full_name if s.teacher else "-",
                s.venue or "-",
            ])
        pdf.table(["Date", "Day", "Time", "Class", "Teacher", "Where"],
                  [26, 20, 36, 52, 30, 22], rows)

    if note:
        pdf.ln(1.5)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*GREY)
        pdf.set_x(12)
        pdf.multi_cell(pdf.w - 24, 4.2, clean(note))


# ── 5. Several teachers, one page each ─────────────────────────────────
def teachers_schedules_pdf(items, start, end):
    """items: list of (teacher, schedules)."""
    _guard()
    pdf = SchedulePDF("Teacher Timetables",
                      f"{start.strftime('%d %b')} to {end.strftime('%d %b %Y')}")
    pdf.alias_nb_pages()
    if not items:
        pdf.add_page()
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 10, "No teachers matched.", ln=1)
        return bytes(pdf.output())
    for teacher, schedules in items:
        pdf.add_page()
        _teacher_block(pdf, teacher, schedules)
    return bytes(pdf.output())


def _teacher_block(pdf, teacher, schedules):
    from collections import defaultdict
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 7, clean(teacher.full_name), ln=1)

    bits = []
    if teacher.subjects:
        bits.append(clean(teacher.subjects))
    hours = getattr(teacher, "hours_label", None)
    if hours and hours != "Not set":
        bits.append(clean(hours))
    if bits:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*GREY)
        for b in bits:
            pdf.set_x(12)
            pdf.multi_cell(pdf.w - 24, 4.5, b)

    live = [s for s in schedules
            if s.class_type not in ("Break", "Other") and s.status != "Cancelled"]
    hrs = sum(s.duration_mins or 0 for s in live) / 60
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 5, f"{len(live)} classes   |   {hrs:.1f} teaching hours", ln=1)

    by_day = defaultdict(list)
    for s in schedules:
        by_day[s.date].append(s)
    if not by_day:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 9.5)
        pdf.cell(0, 6, "Nothing scheduled in this period.", ln=1)
        return

    W = [26, 26, 78, 58, 32, 27]
    H = ["Start", "End", "Class", "Student / group", "Room", "Status"]
    for day in sorted(by_day):
        items = sorted(by_day[day], key=lambda x: x.start_time)
        pdf.section(day.strftime("%A %d %B %Y"))
        rows = [[ampm(s.start_time), ampm(s.end_time), s.task or "-",
                 s.student.full_name if s.student else
                    ("Batch" if s.class_type == "Batch" else "-"),
                 s.room_label, s.status] for s in items]
        pdf.table(H, W, rows)


# ── 6. Daily class routine, one date, for the front desk ───────────────
def daily_routine_pdf(schedules, on_date):
    """Every class on one date with its room. Printed and pinned up."""
    _guard()
    pdf = SchedulePDF("Daily Class Routine",
                      on_date.strftime("%A %d %B %Y"), orientation="P")
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_fill_color(247, 247, 248)
    y0 = pdf.get_y()
    pdf.rect(12, y0, pdf.w - 24, 15, "F")
    pdf.set_xy(15, y0 + 2)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 6.5, clean(on_date.strftime("%A %d %B %Y")), ln=1)
    live = [s for s in schedules if s.status != "Cancelled"]
    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 5, f"{len(live)} class(es)", ln=1)
    pdf.set_y(y0 + 18)

    if not live:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*GREY)
        pdf.cell(0, 8, "No classes scheduled on this date.", ln=1)
        return bytes(pdf.output())

    pdf.section("Timetable")
    rows = []
    for s in sorted(live, key=lambda x: (x.start_time, x.end_time)):
        rows.append([
            f"{ampm(s.start_time)} - {ampm(s.end_time)}",
            s.task or "-",
            s.teacher.full_name if s.teacher else "-",
            "" if s.head_count is None else str(s.head_count),
            s.room_label,
        ])
    pdf.table(["Time", "Class", "Teacher", "Students", "Room"],
              [38, 62, 38, 22, 26], rows, ["L", "L", "L", "C", "L"])
    return bytes(pdf.output())
