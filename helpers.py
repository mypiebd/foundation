"""Shared helpers: clash checking, attendance maths, CSV builders, utilities."""
import os
import csv
import io
import random
import string
from datetime import date, datetime, timedelta
from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user
from sqlalchemy import func

from models import (Announcement, Assessment, Attendance, AuditLog,
                    ClassAssignment, ClassSchedule, Course, Result,
                    ScheduleAttendance, Term, User, db)


# ─────────────────────────────────────────────── auth helpers ────────────────

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def inner(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return inner
    return decorator


def read_only_guard():
    """
    Registered as a before_request hook. The viewer account may look at
    anything it is granted, but any write verb is refused at the door —
    hiding the buttons is not protection.
    """
    if not current_user.is_authenticated:
        return None
    if current_user.role != "STUDENT_VIEWER":
        return None
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.endpoint in ("logout", "login", "change_password"):
            return None
        abort(403, description="This account can view student records but "
                               "cannot change anything.")
    # Block edit/new/delete screens reached by typing the address
    ep = request.endpoint or ""
    for word in ("edit", "new", "delete", "create", "remove", "archive",
                 "reset", "bulk", "enrol", "assign", "mark", "pause",
                 "resume", "stop", "extend", "top_up", "import"):
        if word in ep:
            abort(403, description="This account is read-only.")
    return None


# ─────────────────────────────────────────────── password / ID ───────────────

def make_password(length=8):
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def next_student_id():
    """Auto-incrementing 4-digit numeric username for students."""
    last = (User.query.filter_by(role="STUDENT")
            .order_by(User.id.desc()).first())
    if not last:
        return "1001"
    try:
        return str(int(last.username) + 1)
    except ValueError:
        return str(User.query.filter_by(role="STUDENT").count() + 1001)


def unique_username(base):
    base = base.lower().replace(" ", ".")[:20]
    candidate = base
    n = 1
    while User.query.filter_by(username=candidate).first():
        candidate = f"{base}{n}"
        n += 1
    return candidate


# ─────────────────────────────────────────────── clash checking ──────────────

def time_to_mins(t):
    return t.hour * 60 + t.minute


def minutes_to_time(mins):
    from datetime import time as _time
    return _time((mins // 60) % 24, mins % 60)


def check_teacher_clash(teacher_id, check_date, start_time, end_time,
                        exclude_schedule_id=None):
    """
    Returns dict: status ('green'|'amber'|'red'), message.
    exclude_schedule_id: when editing an existing slot, skip itself.
    """
    s_mins = time_to_mins(start_time)
    e_mins = time_to_mins(end_time)

    q = ClassSchedule.query.filter(
        ClassSchedule.teacher_id == teacher_id,
        ClassSchedule.date == check_date,
        ClassSchedule.status.notin_(["Cancelled"]),
    )
    q = _not_these(q, exclude_schedule_id)
    existing = q.all()

    # ── Hard clash (RED) ────────────────────────────────────────────────────
    for cls in existing:
        if cls.class_type == "Break":
            continue
        ex_s = time_to_mins(cls.start_time)
        ex_e = time_to_mins(cls.end_time)
        if s_mins < ex_e and e_mins > ex_s:
            return {
                "status": "red",
                "message": (f"Double-booked: overlaps with "
                            f'"{cls.task}" ({cls.start_str}–{cls.end_str})')
            }

    # ── Consecutive fatigue (AMBER) ─────────────────────────────────────────
    from types import SimpleNamespace
    day_slots = sorted(
        [c for c in existing if c.class_type not in ("Break", "Other")],
        key=lambda c: time_to_mins(c.start_time)
    )
    probe = SimpleNamespace(start_time=start_time, end_time=end_time)
    all_slots = sorted(day_slots + [probe], key=lambda c: time_to_mins(c.start_time))

    run = 1
    for i in range(1, len(all_slots)):
        gap = time_to_mins(all_slots[i].start_time) - time_to_mins(all_slots[i-1].end_time)
        if gap < 30:
            run += 1
        else:
            run = 1
        if run >= 3:
            return {
                "status": "amber",
                "message": f"Fatigue warning: {run} back-to-back classes with no 30-min break."
            }

    return {"status": "green", "message": "Fully available."}


def _not_these(q, exclude_id):
    """Filter out one schedule id, or a whole set of them."""
    from models import ClassSchedule
    if not exclude_id:
        return q
    if isinstance(exclude_id, (set, frozenset, list, tuple)):
        return q.filter(~ClassSchedule.id.in_(list(exclude_id)))
    return q.filter(ClassSchedule.id != exclude_id)


def check_student_clash(student_id, check_date, start_time, end_time,
                        exclude_schedule_id=None):
    """Returns True if student already has a class overlapping this slot."""
    s_mins = time_to_mins(start_time)
    e_mins = time_to_mins(end_time)
    q = ClassSchedule.query.filter(
        ClassSchedule.student_id == student_id,
        ClassSchedule.date == check_date,
        ClassSchedule.status.notin_(["Cancelled"]),
    )
    q = _not_these(q, exclude_schedule_id)
    for cls in q.all():
        if s_mins < time_to_mins(cls.end_time) and e_mins > time_to_mins(cls.start_time):
            return True
    return False


def generate_slots(start_date, end_date, days_of_week,
                   start_hour, end_hour, duration_mins, num_classes):
    """
    Generate (date, start_time, end_time) tuples.
    days_of_week: list of ints 0=Mon…6=Sun.
    """
    from datetime import time
    slots = []
    current = start_date
    s_mins = start_hour * 60
    e_mins = end_hour * 60
    if s_mins + duration_mins > e_mins:
        e_mins = s_mins + duration_mins
    while current <= end_date and len(slots) < num_classes:
        if current.weekday() in days_of_week:
            s = time(s_mins // 60, s_mins % 60)
            e = time((s_mins + duration_mins) // 60, (s_mins + duration_mins) % 60)
            slots.append((current, s, e))
        current += timedelta(days=1)
    return slots


# ─────────────────────────────────────────────── attendance math ─────────────

def window_from_request():
    """Return (start, end, label) for the current filter window."""
    tid = request.args.get("term_id")
    if tid == "all":
        return date(2000, 1, 1), date(2099, 12, 31), "All time"
    if tid:
        t = db.session.get(Term, int(tid))
        if t:
            return t.start_date, t.end_date, t.name
    current = Term.query.filter_by(is_current=True).first()
    if current:
        return current.start_date, current.end_date, current.name
    return date(2000, 1, 1), date(2099, 12, 31), "All time"


def attendance_summary(student_id, course_id, start, end):
    records = Attendance.query.filter(
        Attendance.student_id == student_id,
        Attendance.course_id == course_id,
        Attendance.date >= start,
        Attendance.date <= end,
    ).all()
    held = len(records)
    attended = sum(1 for r in records if r.status in ("Present", "Late"))
    pct = round(attended / held * 100) if held else 0
    return {"held": held, "attended": attended, "percent": pct}


def bulk_attendance_summary(student_ids, start, end):
    if not student_ids:
        return {}
    rows = (db.session.query(
                Attendance.student_id,
                func.count(Attendance.id).label("held"),
                func.sum(db.case((Attendance.status.in_(["Present", "Late"]), 1), else_=0))
                    .label("attended"))
            .filter(Attendance.student_id.in_(student_ids),
                    Attendance.date >= start,
                    Attendance.date <= end)
            .group_by(Attendance.student_id).all())
    out = {}
    for r in rows:
        pct = round(r.attended / r.held * 100) if r.held else 0
        out[r.student_id] = {"held": r.held, "attended": r.attended, "percent": pct}
    for sid in student_ids:
        if sid not in out:
            out[sid] = {"held": 0, "attended": 0, "percent": 0}
    return out


def average_mark(student_id, course_id=None):
    q = (db.session.query(func.avg(Result.score))
         .join(Assessment, Result.assessment_id == Assessment.id)
         .filter(Result.student_id == student_id, Result.score.isnot(None)))
    if course_id:
        q = q.filter(Assessment.course_id == course_id)
    val = q.scalar()
    if val is None:
        return None
    # as percent of max_score
    mx = (db.session.query(func.avg(Assessment.max_score))
          .join(Result, Result.assessment_id == Assessment.id)
          .filter(Result.student_id == student_id, Result.score.isnot(None)))
    if course_id:
        mx = mx.filter(Assessment.course_id == course_id)
    mx_val = mx.scalar() or 100
    return round(val / mx_val * 100, 1) if mx_val else None


def consecutive_absences(student_id):
    """How many consecutive Absent records the student has most recently."""
    records = (ScheduleAttendance.query
               .filter_by(student_id=student_id)
               .order_by(ScheduleAttendance.marked_at.desc())
               .all())
    streak = 0
    for r in records:
        if r.status == "Absent":
            streak += 1
        else:
            break
    return streak


def students_at_risk(start, end):
    """Students with attendance < 75% or 3+ consecutive absences."""
    ids = [i for (i,) in db.session.query(User.id).filter_by(
        role="STUDENT", status="ACTIVE").all()]
    summaries = bulk_attendance_summary(ids, start, end)
    at_risk = []
    for sid, s in summaries.items():
        consec = consecutive_absences(sid)
        low_att = s["held"] > 0 and s["percent"] < 75
        if low_att or consec >= 3:
            at_risk.append({
                "student": db.session.get(User, sid),
                "percent": s["percent"],
                "held": s["held"],
                "consecutive": consec,
                "low_att": low_att,
            })
    return sorted(at_risk, key=lambda x: x["percent"])


# ─────────────────────────────────────────────── student search ──────────────

def student_search(q="", branch=None, batch_id=None, course_id=None,
                   status="ACTIVE", role="STUDENT"):
    query = User.query.filter_by(role=role)
    if status != "ALL":
        query = query.filter_by(status=status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            User.full_name.ilike(like) |
            User.username.ilike(like) |
            User.phone.ilike(like) |
            User.email.ilike(like)
        )
    if branch:
        query = query.filter_by(branch=branch)
    # batch_id is accepted so older callers still work, but batches were
    # retired in v12 and the column no longer exists, so it filters nothing
    if course_id:
        enrolled_ids = [a.student_id for a in
                        ClassAssignment.query.filter_by(course_id=course_id).all()]
        query = query.filter(User.id.in_(enrolled_ids))
    return query.order_by(User.full_name)


# ─────────────────────────────────────────────── pagination ──────────────────

class Pagination:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, (total + per_page - 1) // per_page)
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1

    def iter_pages(self, edge=2, mid=2):
        pages = []
        for p in range(1, self.pages + 1):
            if (p <= edge or p > self.pages - edge or
                    abs(p - self.page) <= mid):
                pages.append(p)
            elif pages and pages[-1] is not None:
                pages.append(None)
        return pages


def paginate(query, page=None, per_page=50):
    page = page or 1
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return Pagination(items, page, per_page, total)


def page_args():
    args = request.args.to_dict()
    args.pop("page", None)
    return args


# ─────────────────────────────────────────────── announcements ───────────────

def notices_for(user):
    today = date.today()
    q = Announcement.query.filter(
        (Announcement.expires_on.is_(None)) | (Announcement.expires_on >= today)
    )
    if user.is_student:
        q = q.filter(Announcement.audience.in_(["STUDENTS", "EVERYONE"]))
        course_ids = [e.course_id for e in user.enrolments]
        q = q.filter(
            (Announcement.course_id.in_(course_ids)) |
            (Announcement.course_id.is_(None))
        )
    elif user.is_teacher:
        q = q.filter(Announcement.audience.in_(["TEACHERS", "EVERYONE"]))
        my_course_ids = [a.course_id for a in user.teaching_assignments]
        q = q.filter(
            (Announcement.course_id.in_(my_course_ids)) |
            (Announcement.course_id.is_(None))
        )
    return q.order_by(Announcement.is_urgent.desc(),
                      Announcement.created_at.desc()).all()


# ─────────────────────────────────────────────── audit log ───────────────────

def log_action(action, detail=""):
    """
    Record who did what.

    This commits on its own. Most callers log *after* their own commit, so
    merely adding to the session left the entry sitting there and the log
    stayed empty. A failure to write the log must never take the actual
    change down with it, so it is swallowed and reported to the server log.
    """
    try:
        db.session.add(AuditLog(
            actor_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            detail=(detail or "")[:500],
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).warning("audit log write failed: %s", action)


# ─────────────────────────────────────────────── CSV builders ────────────────

def csv_response(filename, headers, rows):
    """Return a Flask Response streaming a CSV file."""
    from flask import Response
    def generate():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(headers)
        for row in rows:
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


def credentials_csv(people):
    rows = [[p.username, p.full_name, p.role, p.initial_password or "(changed)"]
            for p in people]
    return csv_response("credentials.csv",
                        ["Username", "Full Name", "Role", "Initial Password"],
                        rows)


def students_csv(people, summaries):
    rows = []
    for p in people:
        s = summaries.get(p.id, {})
        rows.append([
            p.username, p.full_name, p.phone or "", p.email or "",
            p.branch or "",
            "; ".join(g.name for g in student_classes(p.id)),
            p.status, s.get("held", 0), s.get("attended", 0), s.get("percent", 0)
        ])
    return csv_response("students.csv",
                        ["ID", "Name", "Phone", "Email", "Branch", "Classes",
                         "Status", "Classes Held", "Attended", "Attendance %"],
                        rows)


def schedule_csv(schedules):
    rows = []
    for s in schedules:
        rows.append([
            s.date.strftime("%d-%b-%Y"),
            s.date.strftime("%A"),
            s.start_str,
            s.end_str,
            s.duration_mins,
            s.teacher.full_name if s.teacher else "",
            s.student.full_name if s.student else "",
            s.task or "",
            s.class_type,
            s.venue or "",
            s.status,
        ])
    return csv_response("schedule.csv",
                        ["Date", "Day", "Start", "End", "Duration(mins)",
                         "Teacher", "Student", "Task", "Type", "Venue", "Status"],
                        rows)


def attendance_grid_csv(course, students, dates):
    headers = ["Student ID", "Name"] + [d.strftime("%d-%b") for d in dates]
    rows = []
    for s in students:
        rec = {a.date: a.status for a in
               Attendance.query.filter_by(student_id=s.id, course_id=course.id).all()}
        rows.append([s.username, s.full_name] + [rec.get(d, "") for d in dates])
    return csv_response(f"attendance_{course.course_code}.csv", headers, rows)


def marksheet_csv(course, students, assessments):
    headers = (["Student ID", "Name"] +
               [f"{a.title} ({a.max_score})" for a in assessments])
    rows = []
    for s in students:
        marks = {r.assessment_id: r.score for r in
                 Result.query.filter_by(student_id=s.id).all()}
        rows.append([s.username, s.full_name] +
                    [marks.get(a.id, "") for a in assessments])
    return csv_response(f"marks_{course.course_code}.csv", headers, rows)


# ─────────────────────────────────────────────── storage ────────────────────

def storage_usage():
    import os
    total = 0
    upload_dir = "static/uploads"
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            fp = os.path.join(upload_dir, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  SLOT RESOLUTION ENGINE
#  When a preferred slot is blocked, work out what else would work.
# ═══════════════════════════════════════════════════════════════════════════

OPERATING_START_HOUR = 10      # centre opens
OPERATING_END_HOUR   = 20      # centre closes
SLOT_STEP_MINS       = 30      # granularity when hunting for a free time


def active_teachers():
    return (User.query.filter_by(role="TEACHER", status="ACTIVE")
            .order_by(User.full_name).all())


def slot_verdict(teacher_id, student_id, d, st, en, exclude_id=None):
    """Combined teacher + student check for one slot. Student clash always wins."""
    if student_id and check_student_clash(student_id, d, st, en, exclude_id):
        return {"status": "red",
                "message": "Student already has another class at this time."}
    return check_teacher_clash(teacher_id, d, st, en, exclude_id)


def free_teachers_at(d, st, en, student_id=None, pool=None):
    """Teachers who are not double-booked for this slot, green first."""
    if student_id and check_student_clash(student_id, d, st, en):
        return []                      # student busy — no teacher can help
    out = []
    for t in (pool if pool is not None else active_teachers()):
        if t is None or d.weekday() in t.off_days:
            continue
        span = t.hours_on(d)
        if span and (st < span[0] or en > span[1]):
            continue
        c = check_teacher_clash(t.id, d, st, en)
        if c["status"] != "red":
            out.append({"teacher": t, "status": c["status"], "message": c["message"]})
    out.sort(key=lambda x: 0 if x["status"] == "green" else 1)
    return out


def offset_label(mins):
    """'1h earlier', '30 min later' etc."""
    if mins == 0:
        return "same time"
    sign = "earlier" if mins < 0 else "later"
    a = abs(mins)
    if a % 60 == 0:
        return f"{a // 60}h {sign}"
    if a < 60:
        return f"{a} min {sign}"
    return f"{a // 60}h {a % 60}m {sign}"


def alternative_times(d, requested_start, duration, student_id=None,
                      pool=None, limit=4):
    """
    Nearest times on the SAME day that have at least one free teacher.
    Returned closest-first so the smallest disruption is offered first.
    """
    req = time_to_mins(requested_start)
    cands = []
    m = OPERATING_START_HOUR * 60
    while m + duration <= OPERATING_END_HOUR * 60:
        if m != req:
            st = minutes_to_time(m)
            en = minutes_to_time(m + duration)
            free = free_teachers_at(d, st, en, student_id, pool)
            if free:
                cands.append({
                    "start": st, "end": en,
                    "offset": m - req,
                    "label": offset_label(m - req),
                    "teachers": free,
                    "status": free[0]["status"],
                })
        m += SLOT_STEP_MINS
    cands.sort(key=lambda c: (abs(c["offset"]), 0 if c["status"] == "green" else 1))
    return cands[:limit]


def extension_slots(needed, after_date, days_of_week, start_hour, duration,
                    student_id=None, preferred_teacher_id=None, max_days=180):
    """
    Find `needed` clean slots at the student's PREFERRED day+time, running on
    past `after_date`. This is how we top a series back up to the full count
    without asking the student to change anything.
    """
    if needed <= 0:
        return []
    pool = None
    if preferred_teacher_id:
        t = db.session.get(User, preferred_teacher_id)
        pool = [t] if t else None
    found = []
    st_m  = start_hour * 60
    d     = after_date + timedelta(days=1)
    limit = after_date + timedelta(days=max_days)
    while d <= limit and len(found) < needed:
        if d.weekday() in days_of_week:
            st = minutes_to_time(st_m)
            en = minutes_to_time(st_m + duration)
            free = free_teachers_at(d, st, en, student_id, pool)
            if free:
                found.append({"date": d, "start": st, "en": en, "end": en,
                              "teacher": free[0]["teacher"],
                              "status": free[0]["status"]})
        d += timedelta(days=1)
    return found


def encode_booking(d, st, en, teacher_id):
    """Compact instruction string so confirm needs no recomputation."""
    return f"{d.isoformat()}|{st.strftime('%H:%M')}|{en.strftime('%H:%M')}|{teacher_id}"


def decode_booking(s):
    """Returns (date, start_time, end_time, teacher_id) or None for 'skip'."""
    if not s or s == "skip":
        return None
    try:
        ds, sts, ens, tid = s.split("|")
        y, mo, dy = [int(x) for x in ds.split("-")]
        sh, sm = [int(x) for x in sts.split(":")]
        eh, em = [int(x) for x in ens.split(":")]
        from datetime import time as _t
        return date(y, mo, dy), _t(sh, sm), _t(eh, em), int(tid)
    except (ValueError, AttributeError):
        return None


def build_plan(student_id, start_date, end_date, days_of_week, start_hour,
               duration, num_classes, preferred_teacher_id=None):
    """
    The heart of the wizard. For every requested slot, decide its status and
    — when blocked — gather the alternatives an admin can choose between.
    """
    pool = None
    if preferred_teacher_id:
        t = db.session.get(User, preferred_teacher_id)
        pool = [t] if t else None

    raw = generate_slots(start_date, end_date, days_of_week,
                         start_hour, start_hour + 12, duration, num_classes)
    plan = []
    for idx, (d, st, en) in enumerate(raw):
        free = free_teachers_at(d, st, en, student_id, pool)

        if free:
            # The preferred time works. Assign the best teacher available.
            best = free[0]
            others = free[1:]
            for o in others:
                o["value"] = encode_booking(d, st, en, o["teacher"].id)
            row = {
                "idx": idx, "date": d, "start": st, "end": en,
                "status": best["status"],
                "message": best["message"],
                "teacher": best["teacher"],
                "other_teachers": others,
                "alt_times": [],
                "default": encode_booking(d, st, en, best["teacher"].id),
                "blocked_by_student": False,
            }
        else:
            # Preferred time is blocked. Work out why, and what else fits.
            student_busy = bool(student_id and
                                check_student_clash(student_id, d, st, en))
            if student_busy:
                msg = "Student already has another class at this time."
                same_time = []
            elif preferred_teacher_id:
                # The chosen teacher is busy — is anyone else free at this time?
                same_time = free_teachers_at(d, st, en, student_id, None)
                msg = ("Preferred teacher is booked."
                       if same_time else "Every teacher is booked at this time.")
            else:
                same_time = []
                msg = "Every teacher is booked at this time."

            alts = alternative_times(d, st, duration, student_id, pool)
            if not alts and pool:
                # Widen the hunt: any teacher, any nearby time
                alts = alternative_times(d, st, duration, student_id, None)

            # Encode each alternative so the template just renders it
            for o in same_time:
                o["value"] = encode_booking(d, st, en, o["teacher"].id)
            for a in alts:
                a["value"] = encode_booking(d, a["start"], a["end"],
                                            a["teachers"][0]["teacher"].id)

            # Default: swap the teacher if we can (student keeps their time).
            # Never silently move the student's time — make the admin choose.
            default = (same_time[0]["value"] if same_time else "skip")

            row = {
                "idx": idx, "date": d, "start": st, "end": en,
                "status": "red",
                "message": msg,
                "teacher": None,
                "other_teachers": same_time,
                "alt_times": alts,
                "default": default,
                "blocked_by_student": student_busy,
            }
        plan.append(row)
    return plan

# ═══════════════════════════════════════════════════════════════════════════
#  SCHEDULING ENGINE
#  Working hours, protected blocks, the break rule, and suggestions.
# ═══════════════════════════════════════════════════════════════════════════

BREAK_AFTER      = 2      # this many back-to-back classes...
BREAK_MINS       = 30     # ...then this long a break before the next one
HORIZON_DAYS     = 180    # how far ahead an open-ended group is built
STEP_MINS        = 15     # granularity when hunting for a free time
DAY_NAMES        = ["Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday"]


def fmt(t):
    return t.strftime("%I:%M %p").lstrip("0") if t else ""


def mins(t):
    return t.hour * 60 + t.minute


def to_time(m):
    from datetime import time as _t
    return _t((m // 60) % 24, m % 60)


def busy_on(teacher_id, d, exclude_id=None):
    """Everything already occupying the teacher that day, earliest first."""
    from models import ClassSchedule
    q = ClassSchedule.query.filter(
        ClassSchedule.teacher_id == teacher_id,
        ClassSchedule.date == d,
        ClassSchedule.status != "Cancelled",
    )
    q = _not_these(q, exclude_id)
    return sorted(q.all(), key=lambda c: c.start_time)


def blocks_on(teacher_id, d):
    from models import TeacherBlock
    return [b for b in TeacherBlock.query.filter_by(teacher_id=teacher_id).all()
            if b.applies_on(d)]


def needs_break_before(teacher_id, d, start_time, exclude_id=None):
    """
    Apply the break rule. Returns None when the slot is fine, or the earliest
    minute it could start once the required break is honoured.
    """
    existing = [c for c in busy_on(teacher_id, d, exclude_id)
                if c.class_type != "Break"]
    if not existing:
        return None

    s = mins(start_time)
    # Walk backwards from the proposed start, counting the run of classes
    # that touch each other with no real gap.
    run, cursor = 0, s
    for c in sorted(existing, key=lambda x: mins(x.start_time), reverse=True):
        end = mins(c.end_time)
        if end <= cursor and cursor - end < BREAK_MINS:
            run += 1
            cursor = mins(c.start_time)
        elif end <= cursor:
            break
    if run >= BREAK_AFTER:
        last_end = max(mins(c.end_time) for c in existing
                       if mins(c.end_time) <= s)
        return last_end + BREAK_MINS
    return None


def check_slot(teacher_id, d, start_time, end_time, student_ids=None,
               exclude_id=None):
    """
    The one place a proposed class is judged.
    status: 'ok' | 'break' | 'clash'
    """
    t = db.session.get(User, teacher_id)
    if not t:
        return {"status": "clash", "reason": "teacher", "message": "No such teacher."}

    wd, s, e = d.weekday(), mins(start_time), mins(end_time)

    # 1. Does the teacher work that day?
    if wd in t.off_days:
        return {"status": "clash", "reason": "day-off",
                "message": f"{t.full_name} does not work on {DAY_NAMES[wd]}."}

    # 2. Inside their hours?
    span = t.hours_on(d)
    if span and (start_time < span[0] or end_time > span[1]):
        return {"status": "clash", "reason": "hours",
                "message": (f"{t.full_name} works {fmt(span[0])} to {fmt(span[1])} "
                            f"on {DAY_NAMES[wd]}.")}

    # 3. Protected time?
    for b in blocks_on(teacher_id, d):
        if s < mins(b.end_time) and e > mins(b.start_time):
            return {"status": "clash", "reason": "block",
                    "message": (f"{b.label} is kept clear "
                                f"{fmt(b.start_time)} to {fmt(b.end_time)}.")}

    # 4. Teacher already booked?
    for c in busy_on(teacher_id, d, exclude_id):
        if s < mins(c.end_time) and e > mins(c.start_time):
            return {"status": "clash", "reason": "teacher-busy",
                    "message": (f"{t.full_name} has {c.task or 'a class'} "
                                f"{fmt(c.start_time)} to {fmt(c.end_time)}.")}

    # 5. Any of the students already booked?
    from models import ClassSchedule
    for sid in (student_ids or []):
        q = ClassSchedule.query.filter(
            ClassSchedule.date == d,
            ClassSchedule.status != "Cancelled",
            ClassSchedule.student_id == sid)
        q = _not_these(q, exclude_id)
        for c in q.all():
            if s < mins(c.end_time) and e > mins(c.start_time):
                who = db.session.get(User, sid)
                return {"status": "clash", "reason": "student-busy",
                        "message": (f"{who.full_name if who else 'The student'} "
                                    f"already has a class then.")}

    # 6. The break rule
    earliest = needs_break_before(teacher_id, d, start_time, exclude_id)
    if earliest is not None and s < earliest:
        return {"status": "break", "reason": "break",
                "message": (f"{t.full_name} would have {BREAK_AFTER + 1} classes "
                            f"in a row. Needs a {BREAK_MINS}-minute break first, "
                            f"so the earliest is {fmt(to_time(earliest))}."),
                "earliest": to_time(earliest)}

    return {"status": "ok", "reason": "", "message": "Free."}


def suggest_times(teacher_id, d, duration, student_ids=None, wanted=None,
                  limit=4, exclude_id=None):
    """
    Times that genuinely work on that day, nearest to what was asked first.
    This is what turns a refusal into a choice.
    """
    t = db.session.get(User, teacher_id)
    if not t or d.weekday() in t.off_days:
        return []
    span = t.hours_on(d)
    lo = mins(span[0]) if span else 10 * 60
    hi = mins(span[1]) if span else 20 * 60

    target = mins(wanted) if wanted else lo
    out = []
    m = lo
    while m + duration <= hi:
        st, en = to_time(m), to_time(m + duration)
        if not (wanted and m == target):
            v = check_slot(teacher_id, d, st, en, student_ids, exclude_id)
            if v["status"] == "ok":
                out.append({"start": st, "end": en, "offset": m - target,
                            "label": gap_label(m - target)})
        m += STEP_MINS
    out.sort(key=lambda x: abs(x["offset"]))
    return out[:limit]


def gap_label(delta):
    if delta == 0:
        return "as asked"
    way = "earlier" if delta < 0 else "later"
    a = abs(delta)
    if a < 60:
        return f"{a} min {way}"
    h, m = divmod(a, 60)
    return f"{h}h {way}" if m == 0 else f"{h}h {m}m {way}"


def free_teachers_for(d, start_time, end_time, student_ids=None, pool=None):
    """Teachers who could take this exact slot."""
    out = []
    for t in (pool if pool is not None else active_teachers()):
        v = check_slot(t.id, d, start_time, end_time, student_ids)
        if v["status"] == "ok":
            out.append({"teacher": t, "note": ""})
        elif v["status"] == "break":
            out.append({"teacher": t, "note": v["message"]})
    return out


# ── Building sessions from a group ─────────────────────────────────────────

def clear_orphan_slot_links():
    """
    Null any slot_id that no longer points at a real slot. Harmless to run,
    and keeps the database referentially clean after a timetable swap.
    """
    from models import ClassSchedule, ClassSlot
    live = {s.id for s in ClassSlot.query.all()}
    n = 0
    for c in ClassSchedule.query.filter(ClassSchedule.slot_id.isnot(None)).all():
        if c.slot_id not in live:
            c.slot_id = None
            n += 1
    if n:
        db.session.commit()
    return n


def date_for_count(group_days, start, count, teacher_id=None, end_cap=None):
    """
    How far ahead you have to go to fit `count` classes.

    Walks forward from `start` counting only the days the class actually
    meets, and — when a teacher is given — only the dates they could really
    take. That way "20 classes" means twenty taught classes, not twenty
    calendar slots of which some fall on a day off.
    """
    if not group_days or count < 1:
        return start
    got, d, guard = 0, start, 0
    last = start
    while got < count and guard < 2000:
        guard += 1
        if d.weekday() in group_days:
            ok = True
            if teacher_id:
                t = db.session.get(User, teacher_id)
                if t and d.weekday() in t.off_days:
                    ok = False
            if ok:
                got += 1
                last = d
        d += timedelta(days=1)
        if end_cap and d > end_cap:
            break
    return last


def generate_group(group, upto=None, commit=True):
    """Create the missing sessions for every slot in the group."""
    from models import ClassSchedule
    today = date.today()
    if upto is None:
        upto = (group.end_date if group.end_date
                else today + timedelta(days=HORIZON_DAYS))
    if group.end_date and upto > group.end_date:
        upto = group.end_date

    start = group.start_date
    if group.generated_to and group.generated_to >= start:
        start = group.generated_to + timedelta(days=1)

    sids = [m.student_id for m in group.members]
    solo = sids[0] if group.kind == "1-on-1" and sids else None
    have = {(s.date, s.start_time) for s in group.sessions.all()}
    slots_by_day = {}
    for sl in group.slots:
        slots_by_day.setdefault(sl.weekday, []).append(sl)

    made = clash = off = paused = 0
    d = start
    while d <= upto:
        for sl in slots_by_day.get(d.weekday(), []):
            if (d, sl.start_time) in have:
                continue
            if group.paused_on(d):
                paused += 1
                continue
            v = check_slot(group.teacher_id, d, sl.start_time, sl.end_time, sids)
            if v["status"] == "clash":
                if v["reason"] in ("day-off", "hours", "block"):
                    off += 1
                else:
                    clash += 1
                continue
            db.session.add(ClassSchedule(
                date=d, start_time=sl.start_time, end_time=sl.end_time,
                duration_mins=sl.duration_mins, task=group.name,
                class_type=group.kind, venue=group.venue or "Centre",
                teacher_id=group.teacher_id, student_id=solo,
                course_id=group.course_id, group_id=group.id, slot_id=sl.id,
                status="Scheduled"))
            made += 1
        d += timedelta(days=1)

    group.generated_to = upto
    if commit:
        db.session.commit()
    return {"made": made, "clash": clash, "off": off,
            "paused": paused, "upto": upto}


def top_up_groups(upto=None):
    from models import ClassGroup
    n = 0
    for g in ClassGroup.query.filter_by(status="Active").all():
        n += generate_group(g, upto, commit=False)["made"]
    db.session.commit()
    return n


def pause_group(group, frm, to, note=""):
    from models import ClassSchedule
    q = group.sessions.filter(ClassSchedule.date >= frm,
                              ClassSchedule.status == "Scheduled")
    if to:
        q = q.filter(ClassSchedule.date <= to)
    n = 0
    for s in q.all():
        s.status = "Cancelled"
        n += 1
    group.status = "Paused"
    group.pause_from, group.pause_to = frm, to
    if note:
        group.note = note
    db.session.commit()
    return n


def resume_group(group):
    from models import ClassSchedule
    frm, to = group.pause_from, group.pause_to
    group.status = "Active"
    group.pause_from = group.pause_to = None
    restored = 0
    sids = [m.student_id for m in group.members]
    if frm:
        q = group.sessions.filter(ClassSchedule.date >= max(frm, date.today()),
                                  ClassSchedule.status == "Cancelled")
        if to:
            q = q.filter(ClassSchedule.date <= to)
        for s in q.all():
            v = check_slot(s.teacher_id, s.date, s.start_time, s.end_time,
                           sids, exclude_id=s.id)
            if v["status"] != "clash":
                s.status = "Scheduled"
                restored += 1
    db.session.commit()
    res = generate_group(group)
    return restored, res["made"]


def stop_group(group, from_date=None, note=""):
    from models import ClassSchedule
    frm = from_date or date.today()
    n = 0
    for s in group.sessions.filter(ClassSchedule.date >= frm,
                                   ClassSchedule.status == "Scheduled").all():
        s.status = "Cancelled"
        n += 1
    group.status = "Stopped"
    group.end_date = frm - timedelta(days=1)
    if note:
        group.note = note
    db.session.commit()
    return n


def delete_group_range(group, frm, to=None):
    from models import ClassSchedule
    q = group.sessions.filter(ClassSchedule.date >= max(frm, date.today()))
    if to:
        q = q.filter(ClassSchedule.date <= to)
    n = 0
    for s in q.all():
        db.session.delete(s)
        n += 1
    db.session.commit()
    return n


# ── Day timelines, free gaps, reminders ────────────────────────────────────

def day_timeline(teacher_id, d):
    """Classes and the gaps between them, so a day can be read at a glance."""
    t = db.session.get(User, teacher_id)
    if not t or d.weekday() in t.off_days:
        return {"working": False, "items": [], "warnings": []}

    span = t.hours_on(d)
    lo = mins(span[0]) if span else 10 * 60
    hi = mins(span[1]) if span else 20 * 60

    events = []
    for c in busy_on(teacher_id, d):
        events.append({"type": "class", "start": c.start_time,
                       "end": c.end_time, "obj": c})
    for b in blocks_on(teacher_id, d):
        events.append({"type": "block", "start": b.start_time,
                       "end": b.end_time, "obj": b})
    events.sort(key=lambda x: mins(x["start"]))

    items, cursor, run = [], lo, 0
    for ev in events:
        s, e = mins(ev["start"]), mins(ev["end"])
        if s > cursor:
            items.append({"type": "free", "start": to_time(cursor),
                          "end": to_time(s), "mins": s - cursor})
        if ev["type"] == "class":
            gap_before = s - cursor if items and items[-1]["type"] != "free" else None
            run = run + 1 if (cursor == s and items) else 1
        items.append(ev)
        cursor = max(cursor, e)
    if cursor < hi:
        items.append({"type": "free", "start": to_time(cursor),
                      "end": to_time(hi), "mins": hi - cursor})

    # Flag a run of classes with no real break between them
    warnings, streak, streak_from = [], 0, None
    prev_end = None
    for it in items:
        if it["type"] == "class":
            if prev_end is not None and mins(it["start"]) - prev_end < BREAK_MINS:
                streak += 1
            else:
                streak = 1
                streak_from = it["start"]
            if streak > BREAK_AFTER:
                warnings.append(
                    f"{streak} classes back to back from {fmt(streak_from)} "
                    f"with no {BREAK_MINS}-minute break.")
            prev_end = mins(it["end"])
        elif it["type"] in ("free", "block") and it.get("mins", BREAK_MINS) >= BREAK_MINS:
            streak = 0
            prev_end = None

    teaching = [i for i in items if i["type"] == "class"]
    return {
        "working": True,
        "items": items,
        "warnings": list(dict.fromkeys(warnings)),
        "classes": len(teaching),
        "hours": round(sum((i["obj"].duration_mins or 0) for i in teaching) / 60, 1),
        "free_mins": sum(i["mins"] for i in items if i["type"] == "free"),
        "window": (to_time(lo), to_time(hi)),
    }


def free_slots_today(d=None, min_mins=60, limit=40):
    """Open gaps across every active teacher — the dashboard's 'what's free'."""
    d = d or date.today()
    out = []
    for t in active_teachers():
        tl = day_timeline(t.id, d)
        if not tl["working"]:
            continue
        for it in tl["items"]:
            if it["type"] == "free" and it["mins"] >= min_mins:
                out.append({"teacher": t, "start": it["start"],
                            "end": it["end"], "mins": it["mins"], "date": d})
    out.sort(key=lambda x: (mins(x["start"]), x["teacher"].full_name))
    return out[:limit]


def outstanding_for(teacher_id, days_back=7):
    """
    Classes that have finished but have no attendance or no lesson log.
    This drives the reminders.
    """
    from models import ClassSchedule, LessonLog, ScheduleAttendance
    now = datetime.now()
    today = now.date()
    since = today - timedelta(days=days_back)
    rows = (ClassSchedule.query
            .filter(ClassSchedule.teacher_id == teacher_id,
                    ClassSchedule.date >= since,
                    ClassSchedule.date <= today,
                    ClassSchedule.status == "Scheduled",
                    ClassSchedule.class_type != "Break")
            .order_by(ClassSchedule.date.desc(),
                      ClassSchedule.start_time.desc()).all())
    out = []
    for c in rows:
        finished = datetime.combine(c.date, c.end_time)
        if finished > now:
            continue
        att = ScheduleAttendance.query.filter_by(schedule_id=c.id).count()
        log = 0
        if c.course_id:
            log = LessonLog.query.filter_by(course_id=c.course_id,
                                            class_date=c.date).count()
        if att == 0 or log == 0:
            hrs = (now - finished).total_seconds() / 3600
            out.append({"cls": c, "no_attendance": att == 0,
                        "no_log": log == 0, "hours_ago": round(hrs, 1)})
    return out


def next_dates(weekday, start, count=8, end=None):
    """The next `count` dates falling on that weekday."""
    out = []
    d = max(start, date.today())
    while len(out) < count:
        if end and d > end:
            break
        if d.weekday() == weekday:
            out.append(d)
        d += timedelta(days=1)
        if (d - start).days > 400:
            break
    return out


def analyse_slot(teacher_id, weekday, st, en, student_ids, start, end=None,
                 occurrences=8, exclude_group_id=None):
    """
    Judge one weekly slot over its next few dates, so problems are caught
    before anything is created rather than silently skipped afterwards.

    exclude_group_id ignores a class's own sessions. Without it, re-saving a
    class's existing timetable reports the class as clashing with itself.
    """
    from models import ClassSchedule
    dates = next_dates(weekday, start, occurrences, end)
    if not dates:
        return {"ok": 0, "total": 0, "clean": True, "message": "", "dates": []}
    own = set()
    if exclude_group_id:
        own = {c.id for c in ClassSchedule.query.filter_by(
            group_id=exclude_group_id).all()}
    verdicts = [(d, check_slot(teacher_id, d, st, en, student_ids,
                               exclude_id=own or None)) for d in dates]
    good = [d for d, v in verdicts if v["status"] == "ok"]
    bad  = [(d, v) for d, v in verdicts if v["status"] != "ok"]
    return {
        "ok": len(good),
        "total": len(dates),
        "clean": not bad,
        "message": bad[0][1]["message"] if bad else "",
        "status": bad[0][1]["status"] if bad else "ok",
        "bad_dates": [d for d, _ in bad],
        "sample": bad[0][0] if bad else dates[0],
        "dates": dates,
        # each date with its own verdict, so a screen can say exactly which
        # Friday is free and which is taken rather than just counting them
        "detail": [{"date": d, "status": v["status"], "message": v["message"]}
                   for d, v in verdicts],
    }


def slot_options(teacher_id, sample_date, st, en, student_ids, pool=None):
    """
    What else would work for this slot: other times with the same teacher,
    and other teachers at the same time.
    """
    dur = mins(en) - mins(st)
    times = suggest_times(teacher_id, sample_date, dur, student_ids,
                          wanted=st, limit=4)
    others = []
    for t in (pool if pool is not None else active_teachers()):
        if t.id == teacher_id:
            continue
        v = check_slot(t.id, sample_date, st, en, student_ids)
        if v["status"] == "ok":
            others.append({"teacher": t, "note": ""})
        elif v["status"] == "break":
            others.append({"teacher": t, "note": "needs a break first"})
    return {"times": times, "teachers": others[:5]}


# ═══════════════════════════════════════════════════════════════════════════
#  ROUTINE SERVICES
#  One function per report, used by both the screen and the PDF, so the two
#  can never disagree.
# ═══════════════════════════════════════════════════════════════════════════

def get_student_schedule(student_id, from_date, to_date, include_cancelled=False):
    """
    The classes a student actually attends.

    Authoritative path:
        Student -> GroupStudent -> ClassGroup -> ClassSchedule
    plus any genuinely student-specific occurrence (ClassSchedule.student_id).

    Course enrolment is deliberately NOT used. Being enrolled in GED Social
    Studies means the student studies the subject; it does not mean they sit
    in every other student's one-to-one under it.
    """
    from models import ClassSchedule, GroupStudent

    group_ids = [g.group_id for g in
                 GroupStudent.query.filter_by(student_id=student_id).all()]

    conds = [ClassSchedule.student_id == student_id]
    if group_ids:
        conds.append(ClassSchedule.group_id.in_(group_ids))

    q = (ClassSchedule.query
         .filter(ClassSchedule.date >= from_date,
                 ClassSchedule.date <= to_date)
         .filter(db.or_(*conds)))
    if not include_cancelled:
        q = q.filter(ClassSchedule.status != "Cancelled")

    rows = q.order_by(ClassSchedule.date, ClassSchedule.start_time).all()

    # A student can qualify through both paths; show the class once.
    seen, out = set(), []
    for r in rows:
        if r.id in seen:
            continue
        seen.add(r.id)
        out.append(r)
    return out


def get_daily_schedule(on_date, teacher_id=None, include_cancelled=True):
    """Every class on one date, earliest first — the room-assignment page."""
    from models import ClassSchedule
    q = ClassSchedule.query.filter(ClassSchedule.date == on_date,
                                   ClassSchedule.class_type != "Break")
    if teacher_id:
        q = q.filter(ClassSchedule.teacher_id == teacher_id)
    if not include_cancelled:
        q = q.filter(ClassSchedule.status != "Cancelled")
    return q.order_by(ClassSchedule.start_time, ClassSchedule.end_time).all()


def get_teacher_schedule(teacher_id, from_date, to_date, include_cancelled=True):
    from models import ClassSchedule
    q = (ClassSchedule.query
         .filter(ClassSchedule.teacher_id == teacher_id,
                 ClassSchedule.date >= from_date,
                 ClassSchedule.date <= to_date))
    if not include_cancelled:
        q = q.filter(ClassSchedule.status != "Cancelled")
    return q.order_by(ClassSchedule.date, ClassSchedule.start_time).all()


def update_schedule_rooms(mapping):
    """
    Save typed rooms against dated occurrences. Touches the room field only —
    never the teacher, students, group, course, date, time or pattern, and
    never a future date.
    """
    from models import ClassSchedule
    changed = 0
    for sid, room in mapping.items():
        cls = db.session.get(ClassSchedule, int(sid))
        if not cls:
            continue
        new = (room or "").strip()[:100] or None
        if new != cls.room:
            cls.room = new
            changed += 1
    if changed:
        db.session.commit()
    return changed


def unlinked_schedules(limit=200):
    """
    Occurrences with no group and no student — they cannot appear on anybody's
    routine, so they need repairing rather than papering over.
    """
    from models import ClassSchedule
    return (ClassSchedule.query
            .filter(ClassSchedule.group_id.is_(None),
                    ClassSchedule.student_id.is_(None),
                    ClassSchedule.class_type != "Break")
            .order_by(ClassSchedule.date).limit(limit).all())


# ═══════════════════════════════════════════════════════════════════════════
#  FILE UPLOADS — assignment briefs and student submissions
# ═══════════════════════════════════════════════════════════════════════════

ALLOWED_DOCS  = {"doc", "docx", "pdf", "ppt", "pptx", "xls", "xlsx", "txt", "rtf"}
ALLOWED_IMGS  = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_UPLOAD = ALLOWED_DOCS | ALLOWED_IMGS
BLOCKED_EXT   = {"exe", "bat", "cmd", "com", "sh", "bash", "ps1", "js", "jar",
                 "msi", "vbs", "scr", "dll", "so", "py", "php", "html", "htm",
                 "svg", "apk", "app", "deb", "rpm"}
MAX_UPLOAD_MB = 15


def upload_root():
    """Uploads live outside the template/static tree."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(base, exist_ok=True)
    return base


def ext_of(filename):
    return (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def check_upload(storage):
    """Validate before writing anything. Returns (ok, message, extension)."""
    if not storage or not storage.filename:
        return False, "No file chosen.", ""
    ext = ext_of(storage.filename)
    if not ext:
        return False, "That file has no extension.", ""
    if ext in BLOCKED_EXT:
        return False, f".{ext} files are not allowed.", ext
    if ext not in ALLOWED_UPLOAD:
        return False, (f".{ext} is not a permitted type. Allowed: "
                       f"{', '.join(sorted(ALLOWED_UPLOAD))}."), ext

    storage.stream.seek(0, os.SEEK_END)
    size = storage.stream.tell()
    storage.stream.seek(0)
    if size == 0:
        return False, "That file is empty.", ext
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        return False, (f"That file is {size / 1024 / 1024:.1f} MB. "
                       f"The limit is {MAX_UPLOAD_MB} MB."), ext
    return True, "", ext


def save_upload(storage, folder):
    """
    Write the file under a random key, never the user's own filename.
    Returns (display_name, storage_key, mime, size).
    """
    import uuid
    from werkzeug.utils import secure_filename

    ok, msg, ext = check_upload(storage)
    if not ok:
        raise ValueError(msg)

    safe = secure_filename(storage.filename) or f"file.{ext}"
    key = f"{folder}/{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(upload_root(), key)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    storage.save(dest)
    return safe[:255], key, (storage.mimetype or "")[:120], os.path.getsize(dest)


def upload_path(key):
    """Resolve a stored key, refusing anything that escapes the folder."""
    if not key:
        return None
    root = os.path.realpath(upload_root())
    full = os.path.realpath(os.path.join(root, key))
    if not full.startswith(root + os.sep):
        return None
    return full if os.path.isfile(full) else None


def delete_upload(key):
    p = upload_path(key)
    if p:
        try:
            os.remove(p)
        except OSError:
            pass


def stranded_students():
    """
    Students enrolled on a subject but attached to no class. Their routine
    will be empty until they are put in one. Where the subject has exactly
    one class, the repair is unambiguous and can be offered as one click.
    """
    from models import ClassAssignment, ClassGroup, GroupStudent, User
    out = []
    for s in (User.query.filter_by(role="STUDENT", status="ACTIVE")
              .order_by(User.full_name).all()):
        if GroupStudent.query.filter_by(student_id=s.id).count():
            continue
        courses, suggestions = [], []
        for a in ClassAssignment.query.filter_by(student_id=s.id).all():
            if not a.course:
                continue
            courses.append(a.course)
            groups = (ClassGroup.query
                      .filter_by(course_id=a.course_id, status="Active")
                      .order_by(ClassGroup.id).all())
            batches = [g for g in groups if g.kind == "Batch"]
            if len(batches) == 1:
                suggestions.append(batches[0])
            elif len(groups) == 1:
                suggestions.append(groups[0])
        out.append({"student": s, "courses": courses,
                    "suggest": suggestions,
                    "certain": len(suggestions) == len(courses) and bool(suggestions)})
    return out


def student_courses(student_id, include_archived=False):
    """
    The subjects a student actually studies.

    Union of two paths, because either is a legitimate way in:
        * class membership   Student -> GroupStudent -> ClassGroup -> Course
        * direct enrolment   Student -> ClassAssignment -> Course

    Membership alone is enough. Being in the GED RLA batch means the student
    studies GED RLA, whether or not anybody also created an enrolment row.
    """
    from models import ClassAssignment, Course, GroupStudent

    ids = set()
    for gs in GroupStudent.query.filter_by(student_id=student_id).all():
        if gs.group and gs.group.course_id:
            ids.add(gs.group.course_id)
    for a in ClassAssignment.query.filter_by(student_id=student_id).all():
        if a.course_id:
            ids.add(a.course_id)
    if not ids:
        return []
    q = Course.query.filter(Course.id.in_(ids))
    if not include_archived:
        q = q.filter_by(is_archived=False)
    return q.order_by(Course.course_code).all()


def student_classes(student_id):
    """The class groups a student belongs to, batch and one-to-one alike."""
    from models import GroupStudent
    out = [gs.group for gs in
           GroupStudent.query.filter_by(student_id=student_id).all() if gs.group]
    return sorted(out, key=lambda g: (g.kind, g.name))


def course_students(course_id, teacher_id=None):
    """
    Everyone studying a subject.

    Union of class membership and direct enrolment, exactly as
    student_courses() works in reverse. When teacher_id is given the result is
    narrowed to that teacher's own classes plus their direct enrolments — but
    a teacher who runs no class on the subject still sees everybody, because
    they may have been asked to set or mark the work regardless.
    """
    from models import ClassAssignment, ClassGroup, GroupStudent, User

    ids = set()
    gq = ClassGroup.query.filter_by(course_id=course_id)
    mine = gq.filter_by(teacher_id=teacher_id).all() if teacher_id else []
    groups = mine or gq.all()
    for g in groups:
        for m in GroupStudent.query.filter_by(group_id=g.id).all():
            ids.add(m.student_id)

    aq = ClassAssignment.query.filter_by(course_id=course_id)
    if teacher_id and mine:
        aq = aq.filter_by(teacher_id=teacher_id)
    for a in aq.all():
        ids.add(a.student_id)

    if not ids:
        return []
    return (User.query.filter(User.id.in_(ids), User.role == "STUDENT")
            .order_by(User.full_name).all())


def sync_assessment_rows(assessment):
    """
    Make sure every student on the subject has a row for this piece of work.
    Safe to call repeatedly — it only adds what is missing, and never removes
    a row that already carries a submission or a mark.
    """
    from models import Result
    added = 0
    for s in course_students(assessment.course_id):
        if not Result.query.filter_by(assessment_id=assessment.id,
                                      student_id=s.id).first():
            db.session.add(Result(assessment_id=assessment.id, student_id=s.id))
            added += 1
    if added:
        db.session.commit()
    return added


# ═══════════════════════════════════════════════════════════════════════════
#  RUNNING OUT — classes whose timetable is about to end
# ═══════════════════════════════════════════════════════════════════════════

EXPIRY_SOON_DAYS = 45


def expiring_classes(within_days=EXPIRY_SOON_DAYS, today=None):
    """
    Active classes whose last booked session falls inside the window.

    A class with no end date never appears here — it keeps generating. What
    matters is the last session actually on the timetable, not the end date
    on paper, because generation can stop short of it.
    """
    from models import ClassGroup, ClassSchedule
    today = today or date.today()
    edge = today + timedelta(days=within_days)
    out = []
    for g in ClassGroup.query.filter_by(status="Active").all():
        last = (g.sessions.filter(ClassSchedule.status != "Cancelled")
                .order_by(ClassSchedule.date.desc()).first())
        if not last:
            out.append({"group": g, "last": None, "days": -1,
                        "students": g.student_count})
            continue
        if g.end_date is None and last.date > edge:
            continue
        if last.date <= edge:
            out.append({"group": g, "last": last.date,
                        "days": (last.date - today).days,
                        "students": g.student_count})
    return sorted(out, key=lambda x: (x["days"], x["group"].name))


def backup_database():
    """
    A copy of the live database, named by the moment it was taken.
    Returns (path, filename). The caller sends it and deletes it after.
    """
    import shutil
    import tempfile
    from flask import current_app

    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    src = uri.replace("sqlite:///", "")
    if not src or not os.path.isfile(src):
        raise RuntimeError("The database file could not be found on the server.")
    name = f"pie-backup-{datetime.now().strftime('%Y-%m-%d_%H%M')}.db"
    tmp = os.path.join(tempfile.gettempdir(), name)
    # copy through SQLite so a backup taken mid-write is still consistent
    import sqlite3
    with sqlite3.connect(src) as s, sqlite3.connect(tmp) as d:
        s.backup(d)
    return tmp, name


# ═══════════════════════════════════════════════════════════════════════════
#  WHO IS BUSY, WHO IS FREE
# ═══════════════════════════════════════════════════════════════════════════

def teacher_day_grid(on_date, slot_mins=30):
    """
    One day, every teacher, laid out in equal strips.

    Each strip is "class", "break", "off" (outside their hours or a day off)
    or "free". This is what makes it obvious at a glance who is stacked and
    who has room, which a list of classes never shows.
    """
    from models import ClassSchedule, TeacherBlock

    teachers = active_teachers()
    day_start, day_end = 10 * 60, 20 * 60 + 30
    for t in teachers:
        span = t.hours_on(on_date)
        if span:
            day_start = min(day_start, span[0].hour * 60 + span[0].minute)
            day_end = max(day_end, span[1].hour * 60 + span[1].minute)
    marks = list(range(day_start, day_end, slot_mins))

    rows = []
    for t in teachers:
        span = t.hours_on(on_date)
        classes = (ClassSchedule.query
                   .filter(ClassSchedule.teacher_id == t.id,
                           ClassSchedule.date == on_date,
                           ClassSchedule.status != "Cancelled").all())
        blocks = [b for b in TeacherBlock.query.filter_by(teacher_id=t.id).all()
                  if (b.on_date == on_date
                      or (b.on_date is None and b.weekday == on_date.weekday()))]
        cells, free_mins = [], 0
        for m in marks:
            a, b = m, m + slot_mins
            if not span or a < span[0].hour * 60 + span[0].minute \
                    or b > span[1].hour * 60 + span[1].minute:
                cells.append({"state": "off", "label": ""})
                continue
            hit = next((c for c in classes
                        if c.start_mins < b and c.end_mins > a), None)
            if hit:
                cells.append({"state": "class", "label": hit.task or "Class",
                              "id": hit.id})
                continue
            blk = next((x for x in blocks
                        if x.start_time.hour * 60 + x.start_time.minute < b
                        and x.end_time.hour * 60 + x.end_time.minute > a), None)
            if blk:
                cells.append({"state": "break", "label": blk.label or "Break"})
                continue
            cells.append({"state": "free", "label": ""})
            free_mins += slot_mins

        taught = sum((c.end_mins - c.start_mins) for c in classes
                     if c.class_type != "Break")
        rows.append({
            "teacher": t, "cells": cells,
            "classes": len([c for c in classes if c.class_type != "Break"]),
            "taught_mins": taught, "free_mins": free_mins,
            "working": bool(span),
            "hours": (f"{fmt(span[0])} – {fmt(span[1])}" if span else "not working"),
        })
    rows.sort(key=lambda r: (not r["working"], -r["taught_mins"]))
    return {"marks": marks, "rows": rows, "slot_mins": slot_mins,
            "labels": [to_time(m) for m in marks]}


def free_gaps(on_date, min_mins=60):
    """
    Every usable gap on one date, longest first.

    A gap is time inside a teacher's working hours with no class and no
    protected block. Anything shorter than min_mins is not worth selling.
    """
    from models import ClassSchedule, TeacherBlock

    out = []
    for t in active_teachers():
        span = t.hours_on(on_date)
        if not span:
            continue
        busy = []
        for c in (ClassSchedule.query
                  .filter(ClassSchedule.teacher_id == t.id,
                          ClassSchedule.date == on_date,
                          ClassSchedule.status != "Cancelled").all()):
            busy.append((c.start_mins, c.end_mins))
        for b in TeacherBlock.query.filter_by(teacher_id=t.id).all():
            if b.on_date == on_date or (b.on_date is None
                                        and b.weekday == on_date.weekday()):
                busy.append((b.start_time.hour * 60 + b.start_time.minute,
                             b.end_time.hour * 60 + b.end_time.minute))
        busy.sort()
        merged = []
        for a, z in busy:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], z))
            else:
                merged.append((a, z))
        cur = span[0].hour * 60 + span[0].minute
        close = span[1].hour * 60 + span[1].minute
        raw = []
        for a, z in merged:
            if a - cur >= min_mins:
                raw.append((cur, a))
            cur = max(cur, z)
        if close - cur >= min_mins:
            raw.append((cur, close))

        for a, z in raw:
            # the gap is free of classes, but a booking at the very start may
            # still breach the break-after-two rule, so say so rather than
            # offering a slot that will be refused
            verdict = check_slot(t.id, on_date, to_time(a),
                                 to_time(min(a + 60, z)))
            out.append({"teacher": t, "start": to_time(a), "end": to_time(z),
                        "mins": z - a,
                        "needs_break": verdict["status"] == "break",
                        "note": verdict["message"] if verdict["status"] == "break" else ""})
    return sorted(out, key=lambda g: (-g["mins"], g["teacher"].full_name))


def teacher_week_load(start, days=7):
    """Taught minutes and free minutes per teacher over a week."""
    rows = {}
    for i in range(days):
        d = start + timedelta(days=i)
        grid = teacher_day_grid(d)
        for r in grid["rows"]:
            k = r["teacher"].id
            if k not in rows:
                rows[k] = {"teacher": r["teacher"], "taught": 0, "free": 0,
                           "classes": 0, "days": 0, "per_day": []}
            rows[k]["taught"] += r["taught_mins"]
            rows[k]["free"] += r["free_mins"]
            rows[k]["classes"] += r["classes"]
            rows[k]["days"] += 1 if r["working"] else 0
            rows[k]["per_day"].append({"date": d, "mins": r["taught_mins"],
                                       "working": r["working"]})
    out = list(rows.values())
    busiest = max((r["taught"] for r in out), default=0) or 1
    for r in out:
        r["share"] = round(r["taught"] / busiest * 100)
        total = r["taught"] + r["free"]
        r["used"] = round(r["taught"] / total * 100) if total else 0
    return sorted(out, key=lambda r: -r["taught"])


# ═══════════════════════════════════════════════════════════════════════════
#  HEALTH — what is actually wrong with the timetable, right now
# ═══════════════════════════════════════════════════════════════════════════

def find_clashes(start=None, end=None, limit=None):
    """
    Every real conflict on the timetable.

    The clash checker stops a *new* class being created badly, but nothing
    was ever re-checking what is already booked. Data imported from a
    spreadsheet, a teacher whose days off changed afterwards, a student added
    to a second class — all of these create conflicts that no one is told
    about. This finds them.

    Five kinds, each with enough detail to act on:
      teacher   one teacher in two places at once
      student   one student in two places at once
      day-off   a class on a day the teacher does not work
      hours     a class outside the teacher's working hours
      no-break  more than BREAK_AFTER classes back to back with no real gap
    """
    from collections import defaultdict
    from models import ClassGroup, ClassSchedule, GroupStudent, User

    start = start or date.today()
    q = (ClassSchedule.query
         .filter(ClassSchedule.status != "Cancelled",
                 ClassSchedule.class_type != "Break",
                 ClassSchedule.date >= start))
    if end:
        q = q.filter(ClassSchedule.date <= end)
    rows = q.order_by(ClassSchedule.date, ClassSchedule.start_time).all()

    out = []

    # ── one teacher, two places ─────────────────────────────────────────
    by_teacher = defaultdict(list)
    for c in rows:
        if c.teacher_id:
            by_teacher[(c.teacher_id, c.date)].append(c)
    for (tid, d), items in by_teacher.items():
        items.sort(key=lambda x: (x.start_mins, x.end_mins))
        for a, b in zip(items, items[1:]):
            if b.start_mins < a.end_mins:
                out.append({
                    "kind": "teacher", "date": d,
                    "who": a.teacher.full_name if a.teacher else "?",
                    "who_id": tid,
                    "a": a, "b": b,
                    "detail": (f"{a.task or 'a class'} ({a.start_str}–{a.end_str}) "
                               f"overlaps {b.task or 'a class'} "
                               f"({b.start_str}–{b.end_str})"),
                })

    # ── one student, two places ─────────────────────────────────────────
    members = defaultdict(list)
    for m in GroupStudent.query.all():
        members[m.group_id].append(m.student_id)
    by_student = defaultdict(list)
    for c in rows:
        ids = set()
        if c.student_id:
            ids.add(c.student_id)
        if c.group_id:
            ids.update(members.get(c.group_id, []))
        for sid in ids:
            by_student[(sid, c.date)].append(c)
    for (sid, d), items in by_student.items():
        items.sort(key=lambda x: (x.start_mins, x.end_mins))
        for a, b in zip(items, items[1:]):
            if b.start_mins < a.end_mins:
                who = db.session.get(User, sid)
                out.append({
                    "kind": "student", "date": d,
                    "who": who.full_name if who else "?", "who_id": sid,
                    "a": a, "b": b,
                    "detail": (f"{a.task or 'a class'} ({a.start_str}) "
                               f"clashes with {b.task or 'a class'} ({b.start_str})"),
                })

    # ── on a day off, or outside working hours ──────────────────────────
    for c in rows:
        t = c.teacher
        if not t:
            continue
        if c.date.weekday() in t.off_days:
            out.append({
                "kind": "day-off", "date": c.date, "who": t.full_name,
                "who_id": t.id, "a": c, "b": None,
                "detail": (f"{c.task or 'a class'} at {c.start_str}, but "
                           f"{t.full_name} does not work on "
                           f"{DAY_NAMES[c.date.weekday()]}s"),
            })
            continue
        span = t.hours_on(c.date)
        if span and (c.start_time < span[0] or c.end_time > span[1]):
            out.append({
                "kind": "hours", "date": c.date, "who": t.full_name,
                "who_id": t.id, "a": c, "b": None,
                "detail": (f"{c.task or 'a class'} runs {c.start_str}–{c.end_str}, "
                           f"outside {t.full_name}'s {fmt(span[0])}–{fmt(span[1])}"),
            })

    # ── too many back to back ───────────────────────────────────────────
    #
    # The break rule stops a THIRD class being booked on top of two, but a
    # run can still appear another way: an import, a class moved later, a
    # teacher's hours changed. A teacher with four in a row and no gap is a
    # real welfare problem, so it is reported like any other conflict.
    for (tid, d), items in by_teacher.items():
        items = sorted(items, key=lambda x: (x.start_mins, x.end_mins))
        run = [items[0]]
        runs = []
        for prev, cur in zip(items, items[1:]):
            if cur.start_mins - prev.end_mins < BREAK_MINS:
                run.append(cur)
            else:
                if len(run) > BREAK_AFTER:
                    runs.append(list(run))
                run = [cur]
        if len(run) > BREAK_AFTER:
            runs.append(list(run))

        for r in runs:
            t = r[0].teacher
            gap = r[1].start_mins - r[0].end_mins if len(r) > 1 else 0
            out.append({
                "kind": "no-break", "date": d,
                "who": t.full_name if t else "?", "who_id": tid,
                "a": r[0], "b": r[-1], "run": r,
                "detail": (f"{len(r)} classes back to back, "
                           f"{r[0].start_str} to {r[-1].end_str}"
                           + (f", longest gap {gap} min" if gap else ", no gap at all")
                           + f". The rule allows {BREAK_AFTER} before a "
                             f"{BREAK_MINS}-minute break."),
            })

    out.sort(key=lambda x: (x["date"], x["kind"], x["who"]))
    return out[:limit] if limit else out


def clash_summary(days_ahead=30):
    """Counts only — cheap enough to run on every dashboard load."""
    end = date.today() + timedelta(days=days_ahead)
    rows = find_clashes(date.today(), end)
    out = {"teacher": 0, "student": 0, "day-off": 0, "hours": 0, "no-break": 0}
    for r in rows:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    out["total"] = len(rows)
    out["window"] = days_ahead
    # the soonest one, so the dashboard can say how urgent it is
    out["first"] = rows[0]["date"] if rows else None
    return out


def teacher_load_today(on_date=None):
    """
    A one-line load figure per teacher for the dashboard.
    Busiest first, so an unbalanced day is obvious immediately.
    """
    on_date = on_date or date.today()
    grid = teacher_day_grid(on_date)
    rows = []
    for r in grid["rows"]:
        total = r["taught_mins"] + r["free_mins"]
        rows.append({
            "teacher": r["teacher"], "classes": r["classes"],
            "taught": r["taught_mins"], "free": r["free_mins"],
            "working": r["working"],
            "used": round(r["taught_mins"] / total * 100) if total else 0,
        })
    return rows


def purge_student(student):
    """
    Remove a student and everything that belongs only to them.

    The database enforces nothing on delete, so the app has to. Relying on
    the model's cascades left class memberships behind: the deleted student
    stayed on the class roll as a blank row, the class count was one too high,
    and the class page crashed trying to link to someone who no longer
    existed. This clears every row that refers to the student explicitly.

    Returns a short description of what was removed, for the activity log.
    """
    from models import (Attendance, ClassAssignment, ClassSchedule,
                        GroupStudent, Result, ScheduleAttendance)
    sid = student.id
    removed = {
        "memberships": GroupStudent.query.filter_by(student_id=sid).delete(
            synchronize_session=False),
        "enrolments": ClassAssignment.query.filter_by(student_id=sid).delete(
            synchronize_session=False),
        "marks": Result.query.filter_by(student_id=sid).delete(
            synchronize_session=False),
        "attendance": Attendance.query.filter_by(student_id=sid).delete(
            synchronize_session=False),
        "registers": ScheduleAttendance.query.filter_by(student_id=sid).delete(
            synchronize_session=False),
    }
    # A session booked for this student alone goes with them; a session that
    # belongs to a class keeps running for everyone else, minus this name.
    removed["own sessions"] = (ClassSchedule.query
        .filter(ClassSchedule.student_id == sid,
                ClassSchedule.group_id.is_(None))
        .delete(synchronize_session=False))
    (ClassSchedule.query
        .filter(ClassSchedule.student_id == sid,
                ClassSchedule.group_id.isnot(None))
        .update({"student_id": None}, synchronize_session=False))
    db.session.delete(student)
    return ", ".join(f"{n} {k}" for k, n in removed.items() if n) or "nothing else"


def clean_orphans():
    """
    Remove rows that point at a student who no longer exists.
    Safe to run any time; returns counts so the caller can report them.
    """
    from sqlalchemy import text
    out = {}
    for table in ["group_student", "class_assignment", "result",
                  "attendance", "schedule_attendance"]:
        n = db.session.execute(text(
            f"DELETE FROM {table} WHERE student_id IS NOT NULL "
            f"AND student_id NOT IN (SELECT id FROM user)")).rowcount
        if n:
            out[table] = n
    n = db.session.execute(text(
        "UPDATE class_schedule SET student_id = NULL WHERE student_id IS NOT NULL "
        "AND student_id NOT IN (SELECT id FROM user) AND group_id IS NOT NULL")).rowcount
    if n:
        out["class_schedule (student link cleared)"] = n
    db.session.commit()
    return out
