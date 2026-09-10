"""Shared query, permission and formatting helpers."""

import os
import random
import string
from datetime import date, datetime, timedelta
from functools import wraps

from flask import abort, current_app, request
from flask_login import current_user
from sqlalchemy import func, or_

from models import (Announcement, Assessment, Attendance, Batch,
                    ClassAssignment, Course, CourseMaterial, Result, Term,
                    TeacherOffDay, User, db)

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
                      "txt", "csv", "zip", "png", "jpg", "jpeg", "gif"}
PER_PAGE = 50


# --------------------------------------------------------------- guards ----

def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def teaches(teacher_id, course_id):
    return db.session.query(ClassAssignment.id).filter_by(
        teacher_id=teacher_id, course_id=course_id).first() is not None


def owned_course_or_404(course_id):
    """Load a course the current teacher actually runs."""
    course = db.session.get(Course, course_id)
    if not course:
        abort(404)
    if current_user.is_teacher and not teaches(current_user.id, course.id):
        abort(403)
    return course


def can_view_student(student):
    if current_user.is_admin:
        return True
    if current_user.is_student:
        return current_user.id == student.id
    if current_user.is_teacher:
        mine = {a.course_id for a in current_user.teaching_assignments}
        theirs = {a.course_id for a in student.enrolments}
        return bool(mine & theirs)
    return False


# ----------------------------------------------------------- small utils ----

def parse_date(value, fallback=None):
    if not value:
        return fallback if fallback is not None else date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return fallback if fallback is not None else date.today()


def make_password(length=8):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def next_student_id(offset=0):
    """IDs are YYYYMMDD plus a serial for that day, e.g. 2026090701."""
    prefix = date.today().strftime("%Y%m%d")
    used = set()
    for (name,) in db.session.query(User.username).filter(User.username.like(f"{prefix}%")).all():
        tail = name[len(prefix):]
        if tail.isdigit():
            used.add(int(tail))
    serial = 1
    skipped = 0
    while True:
        if serial not in used:
            if skipped == offset:
                return f"{prefix}{serial:02d}"
            skipped += 1
        serial += 1


def unique_username(base):
    candidate = base or "user"
    n = 1
    while db.session.query(User.id).filter_by(username=candidate).first():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def log_action(action, detail=""):
    from models import AuditLog
    db.session.add(AuditLog(actor_id=current_user.id if current_user.is_authenticated else None,
                            action=action, detail=detail[:500]))


# ------------------------------------------------------------- terms -------

def current_term():
    return Term.query.filter_by(is_current=True).first()


def term_range(term_id=None, start=None, end=None):
    """Resolve a date window from a term id or explicit dates.

    Returns (start, end, label). Either bound may be None, meaning open-ended.
    """
    if start or end:
        return start, end, "Custom range"
    if term_id:
        term = db.session.get(Term, term_id)
        if term:
            return term.start_date, term.end_date, term.name
    term = current_term()
    if term:
        return term.start_date, term.end_date, term.name
    return None, None, "All time"


def window_from_request():
    """Read term/from/to off the query string."""
    term_id = request.args.get("term_id", type=int)
    start = parse_date(request.args.get("from"), fallback=False) or None
    end = parse_date(request.args.get("to"), fallback=False) or None
    if request.args.get("term_id") == "all":
        return None, None, "All time"
    return term_range(term_id, start, end)


# --------------------------------------------------------- attendance ------

def attendance_query(student_id=None, course_id=None, start=None, end=None):
    q = Attendance.query
    if student_id:
        q = q.filter(Attendance.student_id == student_id)
    if course_id:
        q = q.filter(Attendance.course_id == course_id)
    if start:
        q = q.filter(Attendance.date >= start)
    if end:
        q = q.filter(Attendance.date <= end)
    return q


def summarise(records):
    held = len(records)
    present = sum(1 for r in records if r.status == "Present")
    late = sum(1 for r in records if r.status == "Late")
    absent = sum(1 for r in records if r.status == "Absent")
    attended = present + late
    return {"held": held, "present": present, "late": late, "absent": absent,
            "attended": attended,
            "percent": round(attended / held * 100, 1) if held else 0.0}


def attendance_summary(student_id, course_id=None, start=None, end=None):
    return summarise(attendance_query(student_id, course_id, start, end).all())


def bulk_attendance_summary(student_ids, start=None, end=None):
    """One grouped query instead of one per student — matters at 300 students."""
    if not student_ids:
        return {}
    q = (db.session.query(Attendance.student_id, Attendance.status, func.count(Attendance.id))
         .filter(Attendance.student_id.in_(student_ids)))
    if start:
        q = q.filter(Attendance.date >= start)
    if end:
        q = q.filter(Attendance.date <= end)
    rows = q.group_by(Attendance.student_id, Attendance.status).all()

    out = {sid: {"held": 0, "present": 0, "late": 0, "absent": 0,
                 "attended": 0, "percent": 0.0} for sid in student_ids}
    for sid, status, n in rows:
        bucket = out[sid]
        bucket["held"] += n
        bucket[status.lower()] += n
    for bucket in out.values():
        bucket["attended"] = bucket["present"] + bucket["late"]
        if bucket["held"]:
            bucket["percent"] = round(bucket["attended"] / bucket["held"] * 100, 1)
    return out


def is_off_day(teacher_id, on_date):
    return TeacherOffDay.query.filter_by(teacher_id=teacher_id, off_date=on_date).first()


# ------------------------------------------------------------ rosters ------

def courses_for_teacher(teacher_id, include_archived=False):
    q = (Course.query.join(ClassAssignment, ClassAssignment.course_id == Course.id)
         .filter(ClassAssignment.teacher_id == teacher_id))
    if not include_archived:
        q = q.filter(Course.is_archived.is_(False))
    return q.distinct().order_by(Course.course_code).all()


def courses_for_student(student_id):
    return (Course.query.join(ClassAssignment, ClassAssignment.course_id == Course.id)
            .filter(ClassAssignment.student_id == student_id,
                    Course.is_archived.is_(False))
            .distinct().order_by(Course.course_code).all())


def roster(course_id, teacher_id=None):
    q = (User.query.join(ClassAssignment, ClassAssignment.student_id == User.id)
         .filter(ClassAssignment.course_id == course_id, User.status == "ACTIVE"))
    if teacher_id:
        q = q.filter(ClassAssignment.teacher_id == teacher_id)
    return q.order_by(User.full_name).all()


def student_search(q=None, branch=None, batch_id=None, course_id=None,
                   status="ACTIVE", role="STUDENT"):
    """Filtered user query used by the list pages and every export."""
    sel = User.query.filter(User.role == role)
    if status and status != "ALL":
        sel = sel.filter(User.status == status)
    if q:
        like = f"%{q.strip()}%"
        sel = sel.filter(or_(User.full_name.ilike(like), User.username.ilike(like),
                             User.phone.ilike(like), User.email.ilike(like)))
    if branch:
        sel = sel.filter(User.branch == branch)
    if batch_id:
        sel = sel.filter(User.batch_id == batch_id)
    if course_id:
        sel = sel.join(ClassAssignment, ClassAssignment.student_id == User.id) \
                 .filter(ClassAssignment.course_id == course_id)
    return sel.order_by(User.full_name)


# ---------------------------------------------------------- work / marks ---

def open_work_for_student(student_id, limit=None):
    """Published assessments in the student's courses, with their result row."""
    course_ids = [c.id for c in courses_for_student(student_id)]
    if not course_ids:
        return []
    items = (Assessment.query
             .filter(Assessment.course_id.in_(course_ids), Assessment.is_published.is_(True))
             .order_by(Assessment.due_date.is_(None), Assessment.due_date.asc(),
                       Assessment.assigned_date.desc()).all())
    results = {r.assessment_id: r for r in
               Result.query.filter(Result.student_id == student_id).all()}
    rows = [{"assessment": a, "result": results.get(a.id)} for a in items]
    return rows[:limit] if limit else rows


def average_percent(results):
    marked = [r for r in results if r.score is not None and r.assessment.max_score]
    if not marked:
        return None
    total = sum(r.score / r.assessment.max_score for r in marked)
    return round(total / len(marked) * 100, 1)


# ----------------------------------------------------- announcements -------

def _live(query):
    """Drop anything past its expiry date."""
    return query.filter(or_(Announcement.expires_on.is_(None),
                            Announcement.expires_on >= date.today()))


def announcements_for_student(student):
    """Course notices for their courses, plus general ones aimed at them."""
    course_ids = [c.id for c in courses_for_student(student.id)]

    general = _live(Announcement.query.filter(
        Announcement.course_id.is_(None),
        Announcement.audience.in_(["STUDENTS", "EVERYONE"]),
        or_(Announcement.branch.is_(None), Announcement.branch == student.branch),
        or_(Announcement.batch_id.is_(None), Announcement.batch_id == student.batch_id)))

    items = general.all()
    if course_ids:
        items += _live(Announcement.query.filter(
            Announcement.course_id.in_(course_ids))).all()

    items.sort(key=lambda a: (not a.is_urgent, -a.created_at.timestamp()))
    return items


def announcements_for_teacher(teacher):
    """General notices aimed at staff, plus the ones on their own courses."""
    course_ids = [c.id for c in courses_for_teacher(teacher.id)]

    items = _live(Announcement.query.filter(
        Announcement.course_id.is_(None),
        Announcement.audience.in_(["TEACHERS", "EVERYONE"]),
        or_(Announcement.branch.is_(None), Announcement.branch == teacher.branch))).all()

    if course_ids:
        items += _live(Announcement.query.filter(
            Announcement.course_id.in_(course_ids))).all()

    items.sort(key=lambda a: (not a.is_urgent, -a.created_at.timestamp()))
    return items


# ----------------------------------------------------------- storage -------

def storage_usage():
    """Bytes used by uploaded materials, and how that sits against the budget."""
    folder = current_app.config["UPLOAD_FOLDER"]
    total, files = 0, 0
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and not name.startswith("."):
            total += os.path.getsize(path)
            files += 1
    budget = current_app.config["STORAGE_BUDGET"]
    hard = current_app.config["STORAGE_HARD_LIMIT"]
    return {"bytes": total, "files": files, "mb": round(total / 1048576, 1),
            "budget_mb": round(budget / 1048576), "hard_mb": round(hard / 1048576),
            "percent": round(total / hard * 100, 1) if hard else 0,
            "over_budget": total >= budget, "full": total >= hard}


def human_size(n):
    if not n:
        return "—"
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def paginate(query, page):
    return query.paginate(page=page or 1, per_page=PER_PAGE, error_out=False)
