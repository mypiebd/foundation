"""Teacher views. Everything hangs off a single course page."""

import os
from datetime import date, datetime

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from exports import attendance_grid_csv, marksheet_csv
from helpers import (allowed_file, announcements_for_teacher, attendance_query,
                     bulk_attendance_summary, courses_for_teacher, is_off_day,
                     log_action, owned_course_or_404, parse_date, role_required,
                     roster, storage_usage, summarise, window_from_request)
from models import (Announcement, Assessment, ASSESSMENT_KINDS, Attendance,
                    ClassAssignment, Course, CourseMaterial, LessonLog, Result,
                    Term, TeacherOffDay, User, db)

bp = Blueprint("teacher", __name__)
teacher_only = role_required("TEACHER", "ADMIN")


def _terms():
    return Term.query.order_by(Term.start_date.desc()).all()


@bp.route("/teacher")
@login_required
@teacher_only
def my_courses():
    start, end, label = window_from_request()
    courses = courses_for_teacher(current_user.id)
    cards = []
    for c in courses:
        students = roster(c.id, current_user.id)
        records = attendance_query(course_id=c.id, start=start, end=end).all()
        pending = 0
        for a in Assessment.query.filter_by(course_id=c.id, is_published=True).all():
            marked = Result.query.filter(Result.assessment_id == a.id,
                                         Result.score.isnot(None)).count()
            if marked < len(students):
                pending += 1
        last = LessonLog.query.filter_by(course_id=c.id) \
            .order_by(LessonLog.class_date.desc()).first()
        cards.append({"course": c, "students": len(students),
                      "sessions": len({r.date for r in records}),
                      "attendance": summarise(records)["percent"],
                      "pending": pending, "last": last})
    off_days = TeacherOffDay.query.filter(
        TeacherOffDay.teacher_id == current_user.id,
        TeacherOffDay.off_date >= date.today()).order_by(TeacherOffDay.off_date).all()
    return render_template("teacher/courses.html", cards=cards, off_days=off_days,
                           notices=announcements_for_teacher(current_user),
                           window_label=label, terms=_terms())


@bp.route("/teacher/course/<int:course_id>")
@login_required
@teacher_only
def course(course_id):
    course = owned_course_or_404(course_id)
    tab = request.args.get("tab", "register")
    start, end, label = window_from_request()
    students = roster(course.id, None if current_user.is_admin else current_user.id)
    class_date = parse_date(request.args.get("class_date"))

    context = {"course": course, "tab": tab, "students": students,
               "class_date": class_date, "window_label": label, "terms": _terms(),
               "kinds": ASSESSMENT_KINDS,
               "off_day": is_off_day(current_user.id, class_date),
               "storage": storage_usage()}

    if tab == "register":
        context["existing"] = {
            r.student_id: r.status for r in
            Attendance.query.filter_by(course_id=course.id, date=class_date).all()}
        context["summaries"] = bulk_attendance_summary([s.id for s in students], start, end)
        context["marked_dates"] = sorted({
            r.date for r in attendance_query(course_id=course.id, start=start, end=end).all()},
            reverse=True)[:14]

    elif tab == "lessons":
        context["lessons"] = LessonLog.query.filter_by(course_id=course.id) \
            .order_by(LessonLog.class_date.desc(), LessonLog.id.desc()).all()

    elif tab == "work":
        items = Assessment.query.filter_by(course_id=course.id) \
            .order_by(Assessment.assigned_date.desc(), Assessment.id.desc()).all()
        stats = {}
        for a in items:
            rs = Result.query.filter_by(assessment_id=a.id).all()
            stats[a.id] = {"submitted": sum(1 for r in rs if r.submitted_at),
                           "marked": sum(1 for r in rs if r.score is not None),
                           "total": len(students)}
        context["assessments"] = items
        context["stats"] = stats

    elif tab == "marks":
        selected_id = request.args.get("assessment_id", type=int)
        items = Assessment.query.filter_by(course_id=course.id) \
            .order_by(Assessment.assigned_date.desc()).all()
        selected = db.session.get(Assessment, selected_id) if selected_id else None
        if selected and selected.course_id != course.id:
            selected = None
        context["assessments"] = items
        context["selected"] = selected
        if selected:
            context["results"] = {
                r.student_id: r for r in
                Result.query.filter_by(assessment_id=selected.id).all()}

    elif tab == "materials":
        context["materials"] = CourseMaterial.query.filter_by(course_id=course.id) \
            .order_by(CourseMaterial.uploaded_at.desc()).all()

    elif tab == "notices":
        context["notices"] = (Announcement.query
                              .filter_by(course_id=course.id)
                              .order_by(Announcement.created_at.desc()).all())

    elif tab == "students":
        context["summaries"] = bulk_attendance_summary([s.id for s in students], start, end)

    return render_template("teacher/course.html", **context)


# ---------------------------------------------------------- register -------

@bp.route("/teacher/course/<int:course_id>/register", methods=["POST"])
@login_required
@teacher_only
def save_register(course_id):
    course = owned_course_or_404(course_id)
    class_date = parse_date(request.form.get("class_date"))
    if is_off_day(current_user.id, class_date):
        flash("That date is one of your off-days, so attendance can't be marked.", "danger")
        return redirect(url_for("teacher.course", course_id=course.id, tab="register",
                                class_date=class_date.isoformat()))
    if class_date > date.today():
        flash("You can't take a register for a future date.", "danger")
        return redirect(url_for("teacher.course", course_id=course.id, tab="register"))

    saved = 0
    for student in roster(course.id, None if current_user.is_admin else current_user.id):
        status = request.form.get(f"status_{student.id}")
        if status not in ("Present", "Absent", "Late"):
            continue
        record = Attendance.query.filter_by(student_id=student.id, course_id=course.id,
                                            date=class_date).first()
        if record:
            record.status = status
        else:
            db.session.add(Attendance(student_id=student.id, course_id=course.id,
                                      date=class_date, status=status))
        saved += 1
    db.session.commit()
    flash(f"Register saved for {saved} student(s) on {class_date:%d %b %Y}.", "success")
    return redirect(url_for("teacher.course", course_id=course.id, tab="register",
                            class_date=class_date.isoformat()))


@bp.route("/teacher/course/<int:course_id>/attendance.csv")
@login_required
@teacher_only
def attendance_export(course_id):
    course = owned_course_or_404(course_id)
    start, end, _ = window_from_request()
    return attendance_grid_csv(course, roster(course.id), start, end)


# ----------------------------------------------------------- lessons ------

@bp.route("/teacher/course/<int:course_id>/lesson", methods=["POST"])
@login_required
@teacher_only
def log_lesson(course_id):
    course = owned_course_or_404(course_id)
    class_date = parse_date(request.form.get("class_date"))
    topic = request.form.get("topic_taught", "").strip()
    if not topic:
        flash("Write the topic you covered.", "danger")
    elif is_off_day(current_user.id, class_date):
        flash("That date is one of your off-days, so no lesson can be logged.", "danger")
    else:
        db.session.add(LessonLog(course_id=course.id, teacher_id=current_user.id,
                                 class_date=class_date, topic_taught=topic,
                                 summary_notes=request.form.get("summary_notes", "").strip()))
        db.session.commit()
        flash("Lesson posted to the class.", "success")
    return redirect(url_for("teacher.course", course_id=course.id, tab="lessons"))


@bp.route("/teacher/lesson/<int:lesson_id>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_lesson(lesson_id):
    lesson = db.session.get(LessonLog, lesson_id)
    if not lesson:
        abort(404)
    owned_course_or_404(lesson.course_id)
    course_id = lesson.course_id
    db.session.delete(lesson)
    db.session.commit()
    flash("Lesson entry deleted.", "success")
    return redirect(url_for("teacher.course", course_id=course_id, tab="lessons"))


# -------------------------------------------------------------- work ------

@bp.route("/teacher/course/<int:course_id>/work", methods=["POST"])
@login_required
@teacher_only
def create_work(course_id):
    course = owned_course_or_404(course_id)
    title = request.form.get("title", "").strip()
    max_score = request.form.get("max_score", type=float)
    if not title:
        flash("Give the work a title.", "danger")
        return redirect(url_for("teacher.course", course_id=course.id, tab="work"))

    link = request.form.get("attachment_link", "").strip()
    if link and not link.startswith(("http://", "https://")):
        link = "https://" + link

    item = Assessment(
        course_id=course.id, teacher_id=current_user.id, title=title,
        kind=request.form.get("kind") if request.form.get("kind") in ASSESSMENT_KINDS
        else "Assignment",
        instructions=request.form.get("instructions", "").strip(),
        attachment_link=link or None,
        assigned_date=parse_date(request.form.get("assigned_date")),
        due_date=parse_date(request.form.get("due_date"), False) or None,
        max_score=max_score if max_score and max_score > 0 else 100.0,
        needs_submission=request.form.get("needs_submission") == "1",
        is_published=request.form.get("is_published", "1") == "1")
    db.session.add(item)
    db.session.commit()
    flash(f"“{title}” posted. Students see it on their dashboard.", "success")
    return redirect(url_for("teacher.course", course_id=course.id, tab="work"))


@bp.route("/teacher/work/<int:assessment_id>/publish", methods=["POST"])
@login_required
@teacher_only
def toggle_publish(assessment_id):
    item = db.session.get(Assessment, assessment_id)
    if not item:
        abort(404)
    owned_course_or_404(item.course_id)
    item.is_published = not item.is_published
    db.session.commit()
    flash(f"“{item.title}” is now {'visible to' if item.is_published else 'hidden from'} students.",
          "success")
    return redirect(url_for("teacher.course", course_id=item.course_id, tab="work"))


@bp.route("/teacher/work/<int:assessment_id>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_work(assessment_id):
    item = db.session.get(Assessment, assessment_id)
    if not item:
        abort(404)
    owned_course_or_404(item.course_id)
    course_id = item.course_id
    db.session.delete(item)          # cascades to its results
    db.session.commit()
    flash("Work and its marks deleted.", "success")
    return redirect(url_for("teacher.course", course_id=course_id, tab="work"))


# ------------------------------------------------------------- marks ------

@bp.route("/teacher/work/<int:assessment_id>/marks", methods=["POST"])
@login_required
@teacher_only
def save_marks(assessment_id):
    item = db.session.get(Assessment, assessment_id)
    if not item:
        abort(404)
    course = owned_course_or_404(item.course_id)

    saved = 0
    for student in roster(course.id, None if current_user.is_admin else current_user.id):
        raw = request.form.get(f"score_{student.id}", "").strip()
        feedback = request.form.get(f"feedback_{student.id}", "").strip()
        received = request.form.get(f"received_{student.id}") == "1"
        if raw == "" and not feedback and not received:
            continue
        result = Result.query.filter_by(assessment_id=item.id, student_id=student.id).first()
        if not result:
            result = Result(assessment_id=item.id, student_id=student.id)
            db.session.add(result)
        if raw != "":
            try:
                result.score = float(raw)
                result.marked_at = datetime.utcnow()
            except ValueError:
                pass
        if feedback:
            result.feedback = feedback
        if received and not result.submitted_at:
            result.submitted_at = datetime.utcnow()
        saved += 1
    db.session.commit()
    log_action("save_marks", f"{item.course.course_code} · {item.title} · {saved} students")
    flash(f"{saved} entry(s) saved for “{item.title}”.", "success")
    return redirect(url_for("teacher.course", course_id=course.id, tab="marks",
                            assessment_id=item.id))


@bp.route("/teacher/course/<int:course_id>/marksheet.csv")
@login_required
@teacher_only
def marksheet_export(course_id):
    course = owned_course_or_404(course_id)
    assessments = Assessment.query.filter_by(course_id=course.id) \
        .order_by(Assessment.assigned_date).all()
    return marksheet_csv(course, roster(course.id), assessments)


# ----------------------------------------------------------- notices ------

@bp.route("/teacher/course/<int:course_id>/notice", methods=["POST"])
@login_required
@teacher_only
def post_notice(course_id):
    course = owned_course_or_404(course_id)
    title = request.form.get("title", "").strip()
    if not title:
        flash("A notice needs a heading.", "danger")
        return redirect(url_for("teacher.course", course_id=course.id, tab="notices"))

    db.session.add(Announcement(
        author_id=current_user.id, course_id=course.id, audience="STUDENTS",
        title=title, body=request.form.get("body", "").strip(),
        is_urgent=request.form.get("is_urgent") == "1",
        expires_on=parse_date(request.form.get("expires_on"), False) or None))
    db.session.commit()
    flash("Notice posted to the class.", "success")
    return redirect(url_for("teacher.course", course_id=course.id, tab="notices"))


@bp.route("/teacher/notice/<int:notice_id>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_notice(notice_id):
    item = db.session.get(Announcement, notice_id)
    if not item or not item.course_id:
        abort(404)
    owned_course_or_404(item.course_id)
    course_id = item.course_id
    db.session.delete(item)
    db.session.commit()
    flash("Notice removed.", "success")
    return redirect(url_for("teacher.course", course_id=course_id, tab="notices"))


# --------------------------------------------------------- materials ------

@bp.route("/teacher/course/<int:course_id>/material", methods=["POST"])
@login_required
@teacher_only
def add_material(course_id):
    course = owned_course_or_404(course_id)
    title = request.form.get("title", "").strip()
    link = request.form.get("external_link", "").strip()
    upload = request.files.get("file")
    if not title:
        flash("Give the material a title.", "danger")
        return redirect(url_for("teacher.course", course_id=course.id, tab="materials"))

    if link:
        if not link.startswith(("http://", "https://")):
            link = "https://" + link
        db.session.add(CourseMaterial(course_id=course.id, teacher_id=current_user.id,
                                      title=title, file_path_or_link=link, is_link=True))
    elif upload and upload.filename:
        if storage_usage()["full"]:
            flash("Server storage is full. Share this as a link, or ask the office "
                  "to clear old files.", "danger")
            return redirect(url_for("teacher.course", course_id=course.id, tab="materials"))
        if not allowed_file(upload.filename):
            flash("That file type isn't allowed.", "danger")
            return redirect(url_for("teacher.course", course_id=course.id, tab="materials"))
        safe = secure_filename(upload.filename)
        stored = f"{course.id}_{datetime.utcnow():%Y%m%d%H%M%S}_{safe}"
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
        upload.save(path)
        db.session.add(CourseMaterial(course_id=course.id, teacher_id=current_user.id,
                                      title=title, file_path_or_link=stored,
                                      is_link=False, file_size=os.path.getsize(path)))
    else:
        flash("Paste a link or attach a file.", "danger")
        return redirect(url_for("teacher.course", course_id=course.id, tab="materials"))

    db.session.commit()
    flash("Material published to the course.", "success")
    return redirect(url_for("teacher.course", course_id=course.id, tab="materials"))


@bp.route("/teacher/material/<int:material_id>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_material(material_id):
    item = db.session.get(CourseMaterial, material_id)
    if not item:
        abort(404)
    owned_course_or_404(item.course_id)
    course_id = item.course_id
    if not item.is_link:
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], item.file_path_or_link)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(item)
    db.session.commit()
    flash("Material removed.", "success")
    return redirect(url_for("teacher.course", course_id=course_id, tab="materials"))
