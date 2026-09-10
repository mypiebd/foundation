"""Administrator views."""

import os
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from sqlalchemy import func

from exports import (attendance_grid_csv, credentials_csv, marksheet_csv,
                     report_card_pdf, students_csv, PDF_AVAILABLE)
from helpers import (attendance_query, average_percent, bulk_attendance_summary,
                     courses_for_student, log_action, make_password,
                     next_student_id, paginate, parse_date, role_required,
                     roster, storage_usage, student_search, summarise,
                     unique_username, window_from_request, can_view_student)
from models import (Announcement, Assessment, Attendance, Batch, BRANCHES,
                    ClassAssignment, Course, CourseMaterial, LessonLog, Result,
                    Term, User, db)

bp = Blueprint("admin", __name__)
admin_only = role_required("ADMIN")


def _filters():
    return {
        "q": request.args.get("q", "").strip(),
        "branch": request.args.get("branch") or None,
        "batch_id": request.args.get("batch_id", type=int),
        "course_id": request.args.get("course_id", type=int),
        "status": request.args.get("status", "ACTIVE"),
    }


def _existing_student(name):
    """Case-insensitive match on an existing student, active or archived."""
    return User.query.filter(User.role == "STUDENT",
                             func.lower(User.full_name) == name.strip().lower()).first()


def _lists():
    return {
        "batches": Batch.query.filter_by(is_archived=False).order_by(Batch.name).all(),
        "courses": Course.query.filter_by(is_archived=False).order_by(Course.course_code).all(),
        "terms": Term.query.order_by(Term.start_date.desc()).all(),
        "teachers_all": User.query.filter_by(role="TEACHER", status="ACTIVE")
                            .order_by(User.full_name).all(),
    }


# --------------------------------------------------------- dashboard -------

@bp.route("/admin")
@login_required
@admin_only
def overview():
    start, end, label = window_from_request()
    students = db.session.query(func.count(User.id)).filter(
        User.role == "STUDENT", User.status == "ACTIVE").scalar()
    teachers = db.session.query(func.count(User.id)).filter(
        User.role == "TEACHER", User.status == "ACTIVE").scalar()
    courses = db.session.query(func.count(Course.id)).filter(
        Course.is_archived.is_(False)).scalar()

    ids = [i for (i,) in db.session.query(User.id).filter(
        User.role == "STUDENT", User.status == "ACTIVE").all()]
    summaries = bulk_attendance_summary(ids, start, end)
    at_risk = sorted(
        [{"student": db.session.get(User, sid), **s}
         for sid, s in summaries.items() if s["held"] and s["percent"] < 75],
        key=lambda r: r["percent"])[:10]

    unmarked = (Assessment.query
                .outerjoin(Result, Result.assessment_id == Assessment.id)
                .filter(Assessment.is_published.is_(True))
                .group_by(Assessment.id)
                .having(func.count(func.nullif(Result.score, None)) == 0)
                .order_by(Assessment.assigned_date.desc()).limit(6).all())

    # A short setup checklist while the system is still empty.
    enrolments = db.session.query(func.count(ClassAssignment.id)).scalar()
    setup = [
        {"label": "Create a term", "done": Term.query.count() > 0,
         "where": url_for("admin.batches"),
         "why": "Reports then cover this term instead of all time."},
        {"label": "Create a batch", "done": Batch.query.count() > 0,
         "where": url_for("admin.batches"),
         "why": "An intake you can enrol and archive in one click."},
        {"label": "Add your teachers", "done": teachers > 0,
         "where": url_for("admin.teachers"), "why": "They need logins first."},
        {"label": "Add your students", "done": students > 0,
         "where": url_for("admin.students"),
         "why": "Use “Add many” to paste the whole intake at once."},
        {"label": "Create your courses", "done": courses > 0,
         "where": url_for("admin.courses"), "why": "A code and a name each."},
        {"label": "Enrol students in courses", "done": enrolments > 0,
         "where": url_for("admin.courses"),
         "why": "Open a course, pick the teacher, enrol the batch. "
                "Nothing appears for teachers or students until this is done."},
    ]
    show_setup = any(not step["done"] for step in setup)

    return render_template(
        "admin/overview.html", counts={"students": students, "teachers": teachers,
                                       "courses": courses},
        setup=setup, show_setup=show_setup,
        at_risk=at_risk, window_label=label, unmarked=unmarked,
        lessons=LessonLog.query.order_by(LessonLog.class_date.desc(),
                                         LessonLog.id.desc()).limit(8).all(),
        storage=storage_usage(), **_lists())


# ----------------------------------------------------------- students ------

@bp.route("/admin/students")
@login_required
@admin_only
def students():
    f = _filters()
    start, end, label = window_from_request()
    query = student_search(**f)

    duplicates_only = request.args.get("duplicates") == "1"
    if duplicates_only:
        dupe_names = [n for (n,) in db.session.query(func.lower(User.full_name))
                      .filter(User.role == "STUDENT")
                      .group_by(func.lower(User.full_name))
                      .having(func.count(User.id) > 1).all()]
        query = (User.query.filter(User.role == "STUDENT",
                                   func.lower(User.full_name).in_(dupe_names))
                 .order_by(User.full_name, User.id)) if dupe_names else \
                User.query.filter(User.id < 0)

    page = paginate(query, request.args.get("page", type=int))
    summaries = bulk_attendance_summary([s.id for s in page.items], start, end)
    dupe_count = db.session.query(func.count()).select_from(
        db.session.query(func.lower(User.full_name).label("n"))
        .filter(User.role == "STUDENT")
        .group_by(func.lower(User.full_name))
        .having(func.count(User.id) > 1).subquery()).scalar()

    return render_template("admin/students.html", page=page, filters=f,
                           summaries=summaries, window_label=label,
                           duplicates_only=duplicates_only, dupe_count=dupe_count,
                           next_id=next_student_id(), **_lists())


@bp.route("/admin/students/export.csv")
@login_required
@admin_only
def students_export():
    f = _filters()
    start, end, _ = window_from_request()
    people = student_search(**f).all()
    return students_csv(people, bulk_attendance_summary([s.id for s in people], start, end))


@bp.route("/admin/credentials.csv")
@login_required
@admin_only
def credentials_export():
    f = _filters()
    role = request.args.get("role", "STUDENT")
    if role == "TEACHER":
        people = student_search(status=f["status"], role="TEACHER", q=f["q"],
                                branch=f["branch"]).all()
    else:
        people = student_search(**f).all()
    return credentials_csv(people)


@bp.route("/admin/students/new", methods=["POST"])
@login_required
@admin_only
def create_student():
    name = request.form.get("full_name", "").strip()
    if not name:
        flash("A student needs a name.", "danger")
        return redirect(request.referrer or url_for("admin.students"))

    twin = _existing_student(name)
    if twin and request.form.get("create_anyway") != "1":
        flash(f"{name} already exists as {twin.username}. To put them in another "
              f"course, open the course and use Enrol students — don't create a "
              f"second record. If this is a different person with the same name, "
              f"tick “create anyway”.", "danger")
        return redirect(url_for("admin.students", q=name))

    password = make_password()
    student = User(username=next_student_id(), full_name=name, role="STUDENT",
                   phone=request.form.get("phone", "").strip() or None,
                   email=request.form.get("email", "").strip() or None,
                   branch=request.form.get("branch") or None,
                   batch_id=request.form.get("batch_id", type=int),
                   initial_password=password)
    student.set_password(password)
    db.session.add(student)
    db.session.commit()
    flash(f"{name} added — ID {student.username}, password {password}", "success")
    return redirect(url_for("admin.students"))


@bp.route("/admin/students/bulk", methods=["POST"])
@login_required
@admin_only
def bulk_students():
    """One student per line: Name, or Name, phone."""
    raw = request.form.get("names", "")
    branch = request.form.get("branch") or None
    batch_id = request.form.get("batch_id", type=int)
    course_ids = request.form.getlist("course_ids", type=int)
    teacher_id = request.form.get("teacher_id", type=int)

    entries = []
    for line in raw.splitlines():
        line = line.strip().strip(",")
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        entries.append((parts[0], parts[1] if len(parts) > 1 else None))

    if not entries:
        flash("Paste at least one name.", "danger")
        return redirect(url_for("admin.students"))
    if len(entries) > 300:
        flash("That's more than 300 names — split it into smaller batches.", "danger")
        return redirect(url_for("admin.students"))

    force = request.form.get("create_anyway") == "1"
    skipped = []
    if not force:
        kept = []
        for name, phone in entries:
            twin = _existing_student(name)
            if twin:
                skipped.append(f"{name} ({twin.username})")
            else:
                kept.append((name, phone))
        entries = kept
    if not entries:
        flash("Everyone on that list already exists: " + ", ".join(skipped[:10]) +
              ". Enrol them from the course page instead of creating them again.",
              "warning")
        return redirect(url_for("admin.students"))

    created = []
    for i, (name, phone) in enumerate(entries):
        password = make_password()
        student = User(username=next_student_id(offset=i), full_name=name,
                       role="STUDENT", phone=phone or None, branch=branch,
                       batch_id=batch_id, initial_password=password)
        student.set_password(password)
        db.session.add(student)
        created.append(student)
    db.session.commit()

    enrolled = 0
    if course_ids and teacher_id:
        for course_id in course_ids:
            for student in created:
                db.session.add(ClassAssignment(course_id=course_id,
                                               teacher_id=teacher_id,
                                               student_id=student.id))
                enrolled += 1
        db.session.commit()

    log_action("bulk_add_students", f"{len(created)} students")
    msg = f"{len(created)} students created."
    if enrolled:
        msg += f" {enrolled} enrolments added."
    msg += " Download the credential list to hand out logins."
    flash(msg, "success")
    if skipped:
        flash(f"{len(skipped)} skipped — already on file: " + ", ".join(skipped[:10]) +
              ("…" if len(skipped) > 10 else "") +
              ". Enrol them from the course page.", "warning")
    return redirect(url_for("admin.students"))


@bp.route("/admin/people/action", methods=["POST"])
@login_required
@admin_only
def people_action():
    """Archive, restore, reset passwords or permanently delete a selection."""
    action = request.form.get("action")
    ids = request.form.getlist("user_ids", type=int)
    back = request.form.get("back") or url_for("admin.students")
    if not ids:
        flash("Select at least one person first.", "warning")
        return redirect(back)

    people = User.query.filter(User.id.in_(ids), User.role != "ADMIN").all()
    if not people:
        flash("Nothing to do — administrators can't be changed in bulk.", "warning")
        return redirect(back)

    if action == "archive":
        for p in people:
            p.status = "ARCHIVED"
        db.session.commit()
        log_action("archive", f"{len(people)} people")
        flash(f"{len(people)} archived. Their records are kept.", "success")

    elif action == "restore":
        for p in people:
            p.status = "ACTIVE"
        db.session.commit()
        flash(f"{len(people)} restored.", "success")

    elif action == "reset":
        lines = []
        for p in people:
            pw = make_password()
            p.set_password(pw)
            p.initial_password = pw
            lines.append(f"{p.username}: {pw}")
        db.session.commit()
        log_action("reset_passwords", f"{len(people)} people")
        flash("New passwords — " + ", ".join(lines[:10]) +
              (f" and {len(lines) - 10} more in the credential list." if len(lines) > 10 else ""),
              "success")

    elif action == "delete":
        if request.form.get("confirm", "").strip().upper() != "DELETE":
            flash("Type DELETE in the confirmation box to remove records permanently.", "danger")
            return redirect(back)
        names = ", ".join(p.full_name for p in people[:5])
        for p in people:
            db.session.delete(p)      # cascades to attendance, results, enrolments
        db.session.commit()
        log_action("delete_people", names)
        flash(f"{len(people)} deleted permanently, along with their attendance and marks.",
              "success")
    elif action == "merge":
        if len(people) != 2:
            flash("Select exactly two records to merge.", "danger")
            return redirect(back)
        keep, drop = sorted(people, key=lambda p: p.id)
        if keep.role != drop.role:
            flash("Those two aren't the same kind of account.", "danger")
            return redirect(back)
        moved = _merge_users(keep, drop)
        flash(f"Merged into {keep.username} ({keep.full_name}). "
              f"{moved['courses']} enrolment(s), {moved['attendance']} attendance "
              f"record(s) and {moved['results']} mark(s) moved across. "
              f"{drop.username} has been removed.", "success")

    else:
        flash("Unknown action.", "danger")
    return redirect(back)


def _merge_users(keep, drop):
    """Move everything from drop onto keep, then delete drop.

    Where both records already hold the same thing — the same course, the same
    day's attendance, the same assessment — keep's version wins and drop's is
    discarded, so the unique constraints still hold afterwards.
    """
    from models import Attendance, ClassAssignment, Result

    moved = {"courses": 0, "attendance": 0, "results": 0}

    held = {a.course_id for a in ClassAssignment.query.filter_by(student_id=keep.id).all()}
    for a in ClassAssignment.query.filter_by(student_id=drop.id).all():
        if a.course_id in held:
            db.session.delete(a)
        else:
            a.student_id = keep.id
            held.add(a.course_id)
            moved["courses"] += 1

    seen = {(r.course_id, r.date) for r in
            Attendance.query.filter_by(student_id=keep.id).all()}
    for r in Attendance.query.filter_by(student_id=drop.id).all():
        if (r.course_id, r.date) in seen:
            db.session.delete(r)
        else:
            r.student_id = keep.id
            seen.add((r.course_id, r.date))
            moved["attendance"] += 1

    marked = {r.assessment_id for r in Result.query.filter_by(student_id=keep.id).all()}
    for r in Result.query.filter_by(student_id=drop.id).all():
        if r.assessment_id in marked:
            db.session.delete(r)
        else:
            r.student_id = keep.id
            marked.add(r.assessment_id)
            moved["results"] += 1

    # Fill any blanks on the surviving record from the one being removed.
    for field in ("phone", "email", "branch", "batch_id"):
        if not getattr(keep, field) and getattr(drop, field):
            setattr(keep, field, getattr(drop, field))

    db.session.flush()
    log_action("merge_users", f"{drop.username} into {keep.username}")
    db.session.delete(drop)
    db.session.commit()
    return moved


@bp.route("/students/<int:student_id>")
@login_required
def student_profile(student_id):
    """Shared by admin and by teachers who teach the student."""
    student = db.session.get(User, student_id)
    if not student or student.role != "STUDENT":
        abort(404)
    if not can_view_student(student):
        abort(403)
    data = _profile_data(student)
    return render_template("admin/student_profile.html", student=student,
                           pdf_available=PDF_AVAILABLE, **data, **_lists())


@bp.route("/students/<int:student_id>/report.pdf")
@login_required
def student_report(student_id):
    student = db.session.get(User, student_id)
    if not student or student.role != "STUDENT":
        abort(404)
    if not can_view_student(student):
        abort(403)
    data = _profile_data(student)
    data["org_name"] = current_app.config["ORG_NAME"]
    pdf = report_card_pdf(student, data)
    if pdf is None:
        flash("PDF export needs reportlab installed. Use your browser's "
              "Print → Save as PDF on this page instead.", "warning")
        return redirect(url_for("admin.student_profile", student_id=student.id))
    return pdf


def _profile_data(student):
    start, end, label = window_from_request()
    courses = courses_for_student(student.id)

    per_course = []
    for c in courses:
        records = attendance_query(student.id, c.id, start, end).all()
        teacher = (User.query.join(ClassAssignment, ClassAssignment.teacher_id == User.id)
                   .filter(ClassAssignment.course_id == c.id,
                           ClassAssignment.student_id == student.id).first())
        per_course.append({"course": c, "teacher": teacher, **summarise(records)})

    all_records = attendance_query(student.id, None, start, end) \
        .order_by(Attendance.date.desc()).all()
    missed = [r for r in all_records if r.status == "Absent"][:20]

    results = (Result.query.join(Assessment, Result.assessment_id == Assessment.id)
               .filter(Result.student_id == student.id, Result.score.isnot(None))
               .order_by(Assessment.assigned_date.desc()).all())
    if start:
        results = [r for r in results if r.assessment.assigned_date >= start]
    if end:
        results = [r for r in results if r.assessment.assigned_date <= end]

    done = {r.assessment_id for r in Result.query.filter(
        Result.student_id == student.id,
        Result.submitted_at.isnot(None)).all()}
    outstanding = [a for a in Assessment.query.filter(
        Assessment.course_id.in_([c.id for c in courses]) if courses else False,
        Assessment.is_published.is_(True),
        Assessment.needs_submission.is_(True)).all() if a.id not in done] if courses else []

    return {"per_course": per_course, "overall": summarise(all_records),
            "recent": all_records[:30], "missed": missed, "results": results,
            "average": average_percent(results), "outstanding": outstanding,
            "window_label": label, "org_name": current_app.config["ORG_NAME"]}


# ----------------------------------------------------------- teachers ------

@bp.route("/admin/teachers")
@login_required
@admin_only
def teachers():
    f = {"q": request.args.get("q", "").strip(),
         "branch": request.args.get("branch") or None,
         "status": request.args.get("status", "ACTIVE")}
    query = student_search(role="TEACHER", **f)
    page = paginate(query, request.args.get("page", type=int))
    loads = {}
    for t in page.items:
        loads[t.id] = {
            "courses": len({a.course_id for a in t.teaching_assignments}),
            "students": len({a.student_id for a in t.teaching_assignments}),
        }
    from models import TeacherOffDay
    off_days = (TeacherOffDay.query.filter(TeacherOffDay.off_date >= date.today())
                .order_by(TeacherOffDay.off_date).all())
    return render_template("admin/teachers.html", page=page, filters=f, loads=loads,
                           off_days=off_days, **_lists())


@bp.route("/admin/teachers/new", methods=["POST"])
@login_required
@admin_only
def create_teacher():
    name = request.form.get("full_name", "").strip()
    if not name:
        flash("A teacher needs a name.", "danger")
        return redirect(url_for("admin.teachers"))
    username = request.form.get("username", "").strip().lower()
    if not username:
        parts = [p for p in name.lower().split() if p.isalnum()]
        username = (parts[0][0] + parts[-1]) if len(parts) > 1 else (parts[0] if parts else "teacher")
    username = unique_username(username)
    password = make_password()
    teacher = User(username=username, full_name=name, role="TEACHER",
                   phone=request.form.get("phone", "").strip() or None,
                   email=request.form.get("email", "").strip() or None,
                   branch=request.form.get("branch") or None,
                   initial_password=password)
    teacher.set_password(password)
    db.session.add(teacher)
    db.session.commit()
    flash(f"{name} added — username {username}, password {password}", "success")
    return redirect(url_for("admin.teachers"))


@bp.route("/admin/off-days/new", methods=["POST"])
@login_required
@admin_only
def add_off_day():
    from models import TeacherOffDay
    teacher_id = request.form.get("teacher_id", type=int)
    off_date = parse_date(request.form.get("off_date"))
    teacher = db.session.get(User, teacher_id) if teacher_id else None
    if not teacher or teacher.role != "TEACHER":
        flash("Pick a teacher.", "danger")
    elif TeacherOffDay.query.filter_by(teacher_id=teacher.id, off_date=off_date).first():
        flash("That day is already blocked for this teacher.", "warning")
    else:
        db.session.add(TeacherOffDay(teacher_id=teacher.id, off_date=off_date,
                                     reason=request.form.get("reason", "").strip()))
        db.session.commit()
        flash(f"{off_date:%d %b %Y} blocked for {teacher.full_name}.", "success")
    return redirect(url_for("admin.teachers"))


@bp.route("/admin/off-days/<int:off_id>/delete", methods=["POST"])
@login_required
@admin_only
def delete_off_day(off_id):
    from models import TeacherOffDay
    item = db.session.get(TeacherOffDay, off_id)
    if not item:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("Off-day cleared.", "success")
    return redirect(url_for("admin.teachers"))


# ------------------------------------------------------------ courses ------

@bp.route("/admin/courses")
@login_required
@admin_only
def courses():
    show_archived = request.args.get("archived") == "1"
    q = Course.query
    if not show_archived:
        q = q.filter(Course.is_archived.is_(False))
    items = q.order_by(Course.course_code).all()
    stats = {}
    for c in items:
        stats[c.id] = {
            "students": len({a.student_id for a in c.assignments}),
            "teachers": {a.teacher.full_name for a in c.assignments},
            "assessments": len(c.assessments),
        }
    return render_template("admin/courses.html", items=items, stats=stats,
                           show_archived=show_archived, **_lists())


@bp.route("/admin/courses/new", methods=["POST"])
@login_required
@admin_only
def create_course():
    code = request.form.get("course_code", "").strip().upper()
    name = request.form.get("course_name", "").strip()
    if not code or not name:
        flash("A course needs a code and a name.", "danger")
    elif Course.query.filter_by(course_code=code).first():
        flash(f"Course code {code} is already in use.", "danger")
    else:
        db.session.add(Course(course_code=code, course_name=name,
                              description=request.form.get("description", "").strip(),
                              branch=request.form.get("branch") or None))
        db.session.commit()
        flash(f"{code} created. Enrol students from the course page.", "success")
    return redirect(url_for("admin.courses"))


@bp.route("/admin/courses/<int:course_id>")
@login_required
@admin_only
def course_detail(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        abort(404)
    start, end, label = window_from_request()
    enrolled = (User.query.join(ClassAssignment, ClassAssignment.student_id == User.id)
                .filter(ClassAssignment.course_id == course.id)
                .order_by(User.full_name).all())
    summaries = bulk_attendance_summary([s.id for s in enrolled], start, end)
    teacher_by_student = {a.student_id: a.teacher for a in course.assignments}
    candidates = (User.query.filter(User.role == "STUDENT", User.status == "ACTIVE")
                  .order_by(User.full_name).all())
    enrolled_ids = {s.id for s in enrolled}
    return render_template(
        "admin/course_detail.html", course=course, enrolled=enrolled,
        summaries=summaries, teacher_by_student=teacher_by_student,
        candidates=[c for c in candidates if c.id not in enrolled_ids],
        teachers=User.query.filter_by(role="TEACHER", status="ACTIVE")
            .order_by(User.full_name).all(),
        window_label=label,
        assessments=Assessment.query.filter_by(course_id=course.id)
            .order_by(Assessment.assigned_date.desc()).all(), **_lists())


@bp.route("/admin/courses/<int:course_id>/enrol", methods=["POST"])
@login_required
@admin_only
def enrol(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        abort(404)
    teacher_id = request.form.get("teacher_id", type=int)
    student_ids = request.form.getlist("student_ids", type=int)
    batch_id = request.form.get("batch_id", type=int)

    if batch_id:                      # enrol a whole intake in one click
        student_ids += [s.id for s in User.query.filter_by(
            batch_id=batch_id, role="STUDENT", status="ACTIVE").all()]
    teacher = db.session.get(User, teacher_id) if teacher_id else None
    if not teacher or teacher.role != "TEACHER":
        flash("Choose the teacher who runs this class.", "danger")
        return redirect(url_for("admin.course_detail", course_id=course.id))
    if not student_ids:
        flash("Choose at least one student, or a whole batch.", "danger")
        return redirect(url_for("admin.course_detail", course_id=course.id))

    added = moved = 0
    for sid in set(student_ids):
        existing = ClassAssignment.query.filter_by(course_id=course.id, student_id=sid).first()
        if existing:
            if existing.teacher_id != teacher.id:
                existing.teacher_id = teacher.id
                moved += 1
        else:
            db.session.add(ClassAssignment(course_id=course.id, teacher_id=teacher.id,
                                           student_id=sid))
            added += 1
    db.session.commit()
    flash(f"{added} enrolled" + (f", {moved} moved to {teacher.full_name}" if moved else "") + ".",
          "success")
    return redirect(url_for("admin.course_detail", course_id=course.id))


@bp.route("/admin/courses/<int:course_id>/unenrol", methods=["POST"])
@login_required
@admin_only
def unenrol(course_id):
    ids = request.form.getlist("student_ids", type=int)
    n = ClassAssignment.query.filter(ClassAssignment.course_id == course_id,
                                     ClassAssignment.student_id.in_(ids)).delete(
        synchronize_session=False)
    db.session.commit()
    flash(f"{n} enrolment(s) removed. Attendance and marks are kept.", "success")
    return redirect(url_for("admin.course_detail", course_id=course_id))


@bp.route("/admin/courses/<int:course_id>/archive", methods=["POST"])
@login_required
@admin_only
def archive_course(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        abort(404)
    course.is_archived = not course.is_archived
    db.session.commit()
    flash(f"{course.course_code} {'archived' if course.is_archived else 'restored'}.", "success")
    return redirect(url_for("admin.courses"))


# ------------------------------------------------- batches and terms -------

@bp.route("/admin/batches")
@login_required
@admin_only
def batches():
    items = Batch.query.order_by(Batch.start_date.is_(None), Batch.start_date.desc(), Batch.name).all()
    counts = {b.id: len(b.active_students) for b in items}
    return render_template("admin/batches.html", items=items, counts=counts, **_lists())


@bp.route("/admin/batches/new", methods=["POST"])
@login_required
@admin_only
def create_batch():
    name = request.form.get("name", "").strip()
    if not name:
        flash("A batch needs a name, such as 'IFY January 2026'.", "danger")
    elif Batch.query.filter_by(name=name).first():
        flash("That batch already exists.", "danger")
    else:
        db.session.add(Batch(name=name, branch=request.form.get("branch") or None,
                             start_date=parse_date(request.form.get("start_date"), False) or None,
                             end_date=parse_date(request.form.get("end_date"), False) or None))
        db.session.commit()
        flash(f"Batch {name} created.", "success")
    return redirect(url_for("admin.batches"))


@bp.route("/admin/batches/<int:batch_id>/archive", methods=["POST"])
@login_required
@admin_only
def archive_batch(batch_id):
    batch = db.session.get(Batch, batch_id)
    if not batch:
        abort(404)
    batch.is_archived = not batch.is_archived
    also = request.form.get("archive_students") == "1"
    n = 0
    if also and batch.is_archived:
        for s in batch.students:
            s.status = "ARCHIVED"
            n += 1
    db.session.commit()
    flash(f"{batch.name} {'archived' if batch.is_archived else 'restored'}" +
          (f", along with {n} students." if n else "."), "success")
    return redirect(url_for("admin.batches"))


@bp.route("/admin/terms/new", methods=["POST"])
@login_required
@admin_only
def create_term():
    name = request.form.get("name", "").strip()
    start = parse_date(request.form.get("start_date"), False)
    end = parse_date(request.form.get("end_date"), False)
    if not name or not start or not end:
        flash("A term needs a name and both dates.", "danger")
    elif end < start:
        flash("The end date is before the start date.", "danger")
    elif Term.query.filter_by(name=name).first():
        flash("That term already exists.", "danger")
    else:
        term = Term(name=name, start_date=start, end_date=end)
        if request.form.get("is_current") == "1":
            Term.query.update({Term.is_current: False})
            term.is_current = True
        db.session.add(term)
        db.session.commit()
        flash(f"Term {name} created.", "success")
    return redirect(url_for("admin.batches"))


@bp.route("/admin/terms/<int:term_id>/current", methods=["POST"])
@login_required
@admin_only
def set_current_term(term_id):
    term = db.session.get(Term, term_id)
    if not term:
        abort(404)
    Term.query.update({Term.is_current: False})
    term.is_current = True
    db.session.commit()
    flash(f"{term.name} is now the default reporting period.", "success")
    return redirect(url_for("admin.batches"))


# ------------------------------------------------------------ reports ------

@bp.route("/admin/reports")
@login_required
@admin_only
def reports():
    f = _filters()
    start, end, label = window_from_request()
    below = request.args.get("below", type=float)

    people = student_search(**f).all()
    summaries = bulk_attendance_summary([s.id for s in people], start, end)
    rows = [{"student": s, **summaries.get(s.id, {})} for s in people]
    if below is not None:
        rows = [r for r in rows if r.get("held") and r["percent"] < below]
    rows.sort(key=lambda r: (r.get("percent", 0), r["student"].full_name))

    course_rows = []
    for c in Course.query.filter_by(is_archived=False).order_by(Course.course_code).all():
        q = attendance_query(course_id=c.id, start=start, end=end)
        records = q.all()
        sessions = len({r.date for r in records})
        s = summarise(records)
        course_rows.append({"course": c, "sessions": sessions,
                            "enrolled": len({a.student_id for a in c.assignments}), **s})

    return render_template("admin/reports.html", rows=rows, course_rows=course_rows,
                           filters=f, window_label=label, below=below, **_lists())


@bp.route("/admin/reports/attendance/<int:course_id>.csv")
@login_required
@admin_only
def attendance_export(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        abort(404)
    start, end, _ = window_from_request()
    return attendance_grid_csv(course, roster(course.id), start, end)


@bp.route("/admin/reports/marksheet/<int:course_id>.csv")
@login_required
@admin_only
def marksheet_export(course_id):
    course = db.session.get(Course, course_id)
    if not course:
        abort(404)
    assessments = Assessment.query.filter_by(course_id=course.id) \
        .order_by(Assessment.assigned_date).all()
    return marksheet_csv(course, roster(course.id), assessments)


# ------------------------------------------------------------ notices ------

@bp.route("/admin/notices")
@login_required
@admin_only
def notices():
    items = (Announcement.query.order_by(Announcement.created_at.desc()).all())
    live = [a for a in items if not a.is_expired]
    expired = [a for a in items if a.is_expired]
    return render_template("admin/notices.html", live=live, expired=expired,
                           **_lists())


@bp.route("/admin/notices/new", methods=["POST"])
@login_required
@admin_only
def create_notice():
    title = request.form.get("title", "").strip()
    if not title:
        flash("A notice needs a heading.", "danger")
        return redirect(url_for("admin.notices"))

    audience = request.form.get("audience", "STUDENTS")
    if audience not in ("STUDENTS", "TEACHERS", "EVERYONE"):
        audience = "STUDENTS"

    item = Announcement(
        author_id=current_user.id, course_id=None,
        branch=request.form.get("branch") or None,
        batch_id=request.form.get("batch_id", type=int),
        audience=audience, title=title,
        body=request.form.get("body", "").strip(),
        is_urgent=request.form.get("is_urgent") == "1",
        expires_on=parse_date(request.form.get("expires_on"), False) or None)
    db.session.add(item)
    db.session.commit()
    log_action("post_notice", title)
    flash("Notice posted. It shows on their dashboard straight away.", "success")
    return redirect(url_for("admin.notices"))


@bp.route("/admin/notices/<int:notice_id>/delete", methods=["POST"])
@login_required
@admin_only
def delete_notice(notice_id):
    item = db.session.get(Announcement, notice_id)
    if not item:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("Notice removed.", "success")
    return redirect(url_for("admin.notices"))


@bp.route("/admin/notices/<int:notice_id>/expire", methods=["POST"])
@login_required
@admin_only
def expire_notice(notice_id):
    item = db.session.get(Announcement, notice_id)
    if not item:
        abort(404)
    item.expires_on = date.today() - timedelta(days=1)
    db.session.commit()
    flash("Notice taken down. It is kept in the expired list.", "success")
    return redirect(url_for("admin.notices"))


# ------------------------------------------------------------ storage ------

@bp.route("/admin/storage")
@login_required
@admin_only
def storage():
    items = CourseMaterial.query.filter_by(is_link=False) \
        .order_by(CourseMaterial.file_size.desc()).all()
    # Not "links" — base.html sets a template variable of that name for the
    # navigation menu, and it would shadow this one inside the content block.
    link_count = db.session.query(func.count(CourseMaterial.id)).filter(
        CourseMaterial.is_link.is_(True)).scalar()
    return render_template("admin/storage.html", usage=storage_usage(),
                           items=items, link_count=link_count, **_lists())


@bp.route("/admin/storage/<int:material_id>/delete", methods=["POST"])
@login_required
@admin_only
def delete_material(material_id):
    item = db.session.get(CourseMaterial, material_id)
    if not item:
        abort(404)
    if not item.is_link:
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], item.file_path_or_link)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(item)
    db.session.commit()
    flash("File deleted.", "success")
    return redirect(url_for("admin.storage"))
