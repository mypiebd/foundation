"""
Student Records Viewer — front desk, counselling and management.

Look at anything about a student; change nothing. Every write verb is
already refused by read_only_guard in app.py, so this blueprint holds no
POST routes at all.
"""
from datetime import date, timedelta

from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required

from helpers import (attendance_summary, get_student_schedule, notices_for,
                     role_required, student_courses, window_from_request)
from models import (Assessment, Attendance, ClassAssignment, ClassGroup,
                    ClassSchedule, GroupStudent, Result, User, db)

bp = Blueprint("viewer", __name__)

viewer_only = role_required("STUDENT_VIEWER", "ADMIN")


@bp.route("/viewer")
@login_required
@viewer_only
def search():
    """Find a student by name, ID or phone."""
    q = request.args.get("q", "").strip()
    results = []
    if q:
        like = f"%{q}%"
        results = (User.query.filter_by(role="STUDENT")
                   .filter(db.or_(User.full_name.ilike(like),
                                  User.username.ilike(like),
                                  User.phone.ilike(like)))
                   .order_by(User.full_name).limit(60).all())
    rows = []
    for s in results:
        groups = [gs.group for gs in
                  GroupStudent.query.filter_by(student_id=s.id).all()
                  if gs.group]
        rows.append({"s": s, "groups": groups})
    return render_template("viewer/search.html", q=q, rows=rows,
                           total=User.query.filter_by(role="STUDENT",
                                                      status="ACTIVE").count())


def _student_or_404(sid):
    s = db.session.get(User, sid)
    if not s or not s.is_student:
        abort(404)
    return s


@bp.route("/viewer/student/<int:sid>")
@login_required
@viewer_only
def student(sid):
    """Read-only profile with tabs."""
    s = _student_or_404(sid)
    tab = request.args.get("tab", "profile")
    start, end, window_label = window_from_request()
    extra = {}

    memberships = [gs for gs in
                   GroupStudent.query.filter_by(student_id=s.id).all()
                   if gs.group]

    if tab == "classes":
        extra["memberships"] = sorted(
            memberships, key=lambda m: (m.group.kind, m.group.name))
        extra["enrolments"] = (ClassAssignment.query
                               .filter_by(student_id=s.id).all())

    elif tab == "attendance":
        extra["courses"] = [
            {"course": c, "att": attendance_summary(s.id, c.id, start, end)}
            for c in student_courses(s.id)]
        extra["records"] = (Attendance.query
                            .filter(Attendance.student_id == s.id,
                                    Attendance.date >= start,
                                    Attendance.date <= end)
                            .order_by(Attendance.date.desc()).limit(120).all())

    elif tab == "marks":
        extra["results"] = (Result.query.filter_by(student_id=s.id)
                            .join(Assessment)
                            .order_by(Assessment.assigned_date.desc()).all())

    elif tab == "assignments":
        rows = (Result.query.filter_by(student_id=s.id)
                .join(Assessment)
                .order_by(Assessment.due_date.desc().nullslast()).all())
        extra["submissions"] = rows

    elif tab == "routine":
        frm = request.args.get("from")
        to  = request.args.get("to")
        from helpers import parse_date
        r_start = parse_date(frm) or date.today()
        r_end   = parse_date(to) or (r_start + timedelta(days=13))
        extra["routine"] = get_student_schedule(s.id, r_start, r_end)
        extra["r_start"], extra["r_end"] = r_start, r_end

    return render_template("viewer/student.html", student=s, tab=tab,
                           window_label=window_label, **extra)
