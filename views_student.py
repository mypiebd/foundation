"""Student views."""
from datetime import date, datetime, timedelta

from flask import (Blueprint, Response, abort, flash, redirect,
                   render_template, request, send_file, url_for)
from flask_login import current_user, login_required

from helpers import (get_student_schedule, student_classes,
                     student_courses, attendance_summary, average_mark, notices_for,
                     parse_date, role_required, window_from_request, delete_upload,
                     save_upload, upload_path)
from models import (Assessment, Attendance, ClassAssignment, ClassGroup, ClassSchedule,
                    Course, CourseMaterial, GroupStudent, LessonLog, Result,
                    User, db)

bp = Blueprint("student", __name__)
student_only = role_required("STUDENT", "ADMIN")


@bp.route("/student")
@login_required
@student_only
def dashboard():
    start, end, label = window_from_request()
    courses_enrolled = student_courses(current_user.id)
    att_by_course = {
        c.id: attendance_summary(current_user.id, c.id, start, end)
        for c in courses_enrolled
    }
    overall_held     = sum(v["held"]     for v in att_by_course.values())
    overall_attended = sum(v["attended"] for v in att_by_course.values())
    overall_pct      = (round(overall_attended / overall_held * 100)
                        if overall_held else 0)

    avg = average_mark(current_user.id)

    # Pending work
    pending = []
    for c in courses_enrolled:
        for a in Assessment.query.filter_by(course_id=c.id, is_published=True).all():
            r = Result.query.filter_by(
                assessment_id=a.id, student_id=current_user.id).first()
            if r and r.state == "Pending" and a.needs_submission:
                pending.append(r)

    # Every class they are actually in — batch as well as one-to-one
    upcoming = get_student_schedule(
        current_user.id, date.today(), date.today() + timedelta(days=60))[:10]

    return render_template("student/dashboard.html",
                           courses=courses_enrolled,
                           att=att_by_course,
                           overall={"held": overall_held, "attended": overall_attended,
                                    "percent": overall_pct},
                           average=avg,
                           pending=pending,
                           upcoming=upcoming,
                           notices=notices_for(current_user),
                           window_label=label)


@bp.route("/student/course/<int:cid>")
@login_required
@student_only
def course(cid):
    # A student reaches a subject through class membership or direct enrolment
    c = db.session.get(Course, cid)
    if not c:
        abort(404)
    allowed = [x.id for x in student_courses(current_user.id, include_archived=True)]
    if cid not in allowed and not current_user.is_admin:
        abort(403)
    start, end, label = window_from_request()
    att = attendance_summary(current_user.id, cid, start, end)
    # every way this subject is taught, so a student on both sees both
    course_classes = (ClassGroup.query.filter_by(course_id=cid, status="Active")
                      .order_by(ClassGroup.kind, ClassGroup.name).all())

    att_records = (Attendance.query
                   .filter_by(student_id=current_user.id, course_id=cid)
                   .order_by(Attendance.date.desc()).all())

    logs = (LessonLog.query.filter_by(course_id=cid)
            .order_by(LessonLog.class_date.desc()).all())

    assessments = (Assessment.query
                   .filter_by(course_id=cid, is_published=True)
                   .order_by(Assessment.assigned_date.desc()).all())

    results = {r.assessment_id: r for r in
               Result.query.filter_by(student_id=current_user.id).all()}

    materials = (CourseMaterial.query.filter_by(course_id=cid)
                 .order_by(CourseMaterial.uploaded_at.desc()).all())

    return render_template("student/course.html", course_classes=course_classes,
                           course=c, att=att,
                           att_records=att_records,
                           logs=logs,
                           assessments=assessments,
                           results=results,
                           materials=materials,
                           window_label=label)


@bp.route("/student/submit/<int:aid>", methods=["POST"])
@login_required
@student_only
def submit(aid):
    """Hand work in — a file, a link, or both."""
    a = db.session.get(Assessment, aid)
    if not a:
        abort(404)
    if not a.is_published:
        flash("That assignment is not open.", "danger")
        return redirect(url_for("student.dashboard"))

    link = request.form.get("submission_link", "").strip()
    note = request.form.get("student_note", "").strip()
    up   = request.files.get("submission_file")
    has_file = bool(up and up.filename)

    if not link and not has_file:
        flash("Attach your file, or paste a link to it.", "danger")
        return redirect(url_for("student.course", cid=a.course_id))

    r = Result.query.filter_by(
        assessment_id=aid, student_id=current_user.id).first()
    if not r:
        r = Result(assessment_id=aid, student_id=current_user.id)
        db.session.add(r)
        db.session.flush()

    if r.score is not None:
        flash("This has already been marked, so it cannot be replaced. "
              "Speak to your teacher.", "danger")
        return redirect(url_for("student.course", cid=a.course_id))

    if has_file:
        try:
            nm, key, mime, size = save_upload(up, "submissions")
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("student.course", cid=a.course_id))
        if r.file_key:
            delete_upload(r.file_key)          # replace, do not accumulate
        r.file_name, r.file_key = nm, key
        r.file_mime, r.file_size = mime, size

    if link:
        r.submission_link = link
    if note:
        r.student_note = note
    r.submitted_at = datetime.utcnow()
    # a fresh hand-in resets the teacher's acknowledgement
    r.received, r.received_at, r.received_by = False, None, None
    db.session.commit()

    flash("Handed in" + (f" — {r.file_name}" if has_file else "")
          + ". Your teacher will confirm they have it.", "success")
    return redirect(url_for("student.course", cid=a.course_id))


@bp.route("/student/file/assignment/<int:aid>")
@login_required
@student_only
def download_brief(aid):
    """The teacher's attached brief, for a student on that course."""
    a = db.session.get(Assessment, aid)
    if not a or not a.attachment_key or not a.is_published:
        abort(404)
    mine = ClassAssignment.query.filter_by(
        course_id=a.course_id, student_id=current_user.id).first()
    in_group = False
    for gs in GroupStudent.query.filter_by(student_id=current_user.id).all():
        if gs.group and gs.group.course_id == a.course_id:
            in_group = True
            break
    if not (mine or in_group or current_user.is_admin):
        abort(403)
    p = upload_path(a.attachment_key)
    if not p:
        abort(404)
    return send_file(p, as_attachment=True, download_name=a.attachment_name)


@bp.route("/student/file/mine/<int:rid>")
@login_required
@student_only
def download_mine(rid):
    """A student may only ever fetch their own submission."""
    r = db.session.get(Result, rid)
    if not r or not r.file_key:
        abort(404)
    if r.student_id != current_user.id and not current_user.is_admin:
        abort(403)
    p = upload_path(r.file_key)
    if not p:
        abort(404)
    return send_file(p, as_attachment=True, download_name=r.file_name)


@bp.route("/student/routine.pdf")
@login_required
@student_only
def my_routine_pdf():
    """The student downloads their own routine."""
    from datetime import timedelta
    from flask import Response, abort, flash, redirect, url_for
    from helpers import parse_date
    from models import ClassAssignment, ClassGroup, ClassSchedule, User
    try:
        from pdf_export import student_routine_pdf
    except Exception:
        flash("PDF export needs the fpdf2 package. Run: pip install fpdf2", "danger")
        return redirect(url_for("student.dashboard"))

    sid = request.args.get("student_id", type=int) if current_user.is_admin else None
    sid = sid or current_user.id
    student = db.session.get(User, sid)
    if not student:
        abort(404)

    start = parse_date(request.args.get("start")) or date.today()
    end   = parse_date(request.args.get("end")) or (start + timedelta(days=30))

    rows = (ClassSchedule.query
            .filter(ClassSchedule.date >= start, ClassSchedule.date <= end)
            .filter((ClassSchedule.student_id == sid) |
                    (ClassSchedule.course_id.in_(
                        db.session.query(ClassAssignment.course_id)
                        .filter(ClassAssignment.student_id == sid))))
            .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
    try:
        data = student_routine_pdf(student, rows, start, end)
    except RuntimeError:
        flash("PDF export needs the fpdf2 package.", "danger")
        return redirect(url_for("student.dashboard"))
    safe = student.full_name.replace(" ", "_").replace(",", "")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"attachment; filename=my_routine_{safe}.pdf"})
