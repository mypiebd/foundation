"""Student views."""

from datetime import date, datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from helpers import (announcements_for_student, attendance_query,
                     average_percent, courses_for_student,
                     open_work_for_student, role_required, summarise,
                     window_from_request)
from models import (Assessment, ClassAssignment, CourseMaterial, LessonLog,
                    Result, Term, User, db)

bp = Blueprint("student", __name__)
student_only = role_required("STUDENT")


@bp.route("/student")
@login_required
@student_only
def dashboard():
    start, end, label = window_from_request()
    courses = courses_for_student(current_user.id)
    course_ids = [c.id for c in courses]

    per_course = []
    for c in courses:
        records = attendance_query(current_user.id, c.id, start, end).all()
        teacher = (User.query.join(ClassAssignment, ClassAssignment.teacher_id == User.id)
                   .filter(ClassAssignment.course_id == c.id,
                           ClassAssignment.student_id == current_user.id).first())
        per_course.append({"course": c, "teacher": teacher, **summarise(records)})

    work = open_work_for_student(current_user.id)
    due = [w for w in work
           if w["assessment"].needs_submission and
           (w["result"] is None or w["result"].submitted_at is None)]
    marked = [w for w in work if w["result"] is not None and w["result"].score is not None]

    lessons, materials = [], []
    if course_ids:
        lessons = (LessonLog.query.filter(LessonLog.course_id.in_(course_ids))
                   .order_by(LessonLog.class_date.desc(), LessonLog.id.desc())
                   .limit(40).all())
        materials = (CourseMaterial.query.filter(CourseMaterial.course_id.in_(course_ids))
                     .order_by(CourseMaterial.uploaded_at.desc()).all())

    return render_template(
        "student/dashboard.html",
        notices=announcements_for_student(current_user),
        overall=summarise(attendance_query(current_user.id, None, start, end).all()),
        per_course=per_course, work=work, due=due, marked=marked,
        average=average_percent([w["result"] for w in marked]),
        lessons=lessons, materials=materials, courses=courses,
        window_label=label, terms=Term.query.order_by(Term.start_date.desc()).all())


@bp.route("/student/work/<int:assessment_id>/submit", methods=["POST"])
@login_required
@student_only
def submit(assessment_id):
    item = db.session.get(Assessment, assessment_id)
    if not item or not item.is_published:
        abort(404)
    enrolled = ClassAssignment.query.filter_by(course_id=item.course_id,
                                               student_id=current_user.id).first()
    if not enrolled:
        abort(403)

    link = request.form.get("submission_link", "").strip()
    if not link:
        flash("Paste the link to your work.", "danger")
        return redirect(url_for("student.dashboard"))
    if not link.startswith(("http://", "https://")):
        link = "https://" + link

    result = Result.query.filter_by(assessment_id=item.id, student_id=current_user.id).first()
    if not result:
        result = Result(assessment_id=item.id, student_id=current_user.id)
        db.session.add(result)
    result.submission_link = link
    result.submitted_at = datetime.utcnow()
    db.session.commit()

    late = item.due_date and date.today() > item.due_date
    flash("Submitted." + (" It's past the due date, so your teacher will see it as late."
                          if late else " Your teacher can see it now."), "success")
    return redirect(url_for("student.dashboard"))
