"""Administrator views."""
import json
import os
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_file, url_for)
from flask_login import current_user, login_required
from sqlalchemy import func

from helpers import (BREAK_AFTER, BREAK_MINS, active_teachers,
                     clear_orphan_slot_links,
                     analyse_slot, date_for_count, get_daily_schedule,
                     get_student_schedule,
                     backup_database, expiring_classes,
                     get_teacher_schedule, slot_options, stranded_students,
                     student_courses,
                     unlinked_schedules,
                     update_schedule_rooms,
                     attendance_grid_csv, attendance_summary,
                     bulk_attendance_summary, check_slot, consecutive_absences,
                     credentials_csv, day_timeline, delete_group_range, fmt,
                     free_slots_today, free_teachers_for, generate_group,
                     human_size, log_action, make_password, marksheet_csv,
                     mins, next_student_id, notices_for, outstanding_for,
                     page_args, paginate, parse_date, pause_group,
                     resume_group, role_required, schedule_csv, stop_group,
                     storage_usage, student_search, students_at_risk,
                     students_csv, suggest_times, to_time, top_up_groups,
                     unique_username, window_from_request)
from models import (ASSESSMENT_KINDS, BRANCHES, COURSES_LIST, Announcement,
                    ClassGroup, ClassSlot, GroupStudent, TeacherBlock,
                    Assessment, Attendance, AuditLog, ClassAssignment,
                    ClassSchedule, Course, CourseMaterial, LessonLog, Result,
                    ScheduleAttendance, Term, User, db)

bp = Blueprint("admin", __name__)
admin_only = role_required("ADMIN")


def _lists():
    return {
        "courses":      Course.query.filter_by(is_archived=False).order_by(Course.course_code).all(),
        "terms":        Term.query.order_by(Term.start_date.desc()).all(),
        "teachers_all": User.query.filter_by(role="TEACHER", status="ACTIVE")
                            .order_by(User.full_name).all(),
    }


def _filters():
    return {
        "q":        request.args.get("q", "").strip(),
        "branch":   request.args.get("branch") or None,
        "course_id":request.args.get("course_id", type=int),
        "status":   request.args.get("status", "ACTIVE"),
    }


# ═══════════════════════════════════════════════════ DASHBOARD ════════════

@bp.route("/admin")
@login_required
@admin_only
def overview():
    start, end, label = window_from_request()
    today = date.today()

    counts = {
        "students": User.query.filter_by(role="STUDENT", status="ACTIVE").count(),
        "teachers": User.query.filter_by(role="TEACHER", status="ACTIVE").count(),
        "courses":  Course.query.filter_by(is_archived=False).count(),
        "groups":   ClassGroup.query.filter_by(status="Active").count(),
    }
    todays = (ClassSchedule.query.filter_by(date=today)
              .order_by(ClassSchedule.start_time).all())
    counts["today"] = len([c for c in todays if c.status != "Cancelled"])

    # Anything finished but not written up, across every teacher
    pending = []
    for t in active_teachers():
        for item in outstanding_for(t.id, days_back=3):
            item["teacher"] = t
            pending.append(item)
    pending.sort(key=lambda x: -x["hours_ago"])

    free = free_slots_today(today, min_mins=60)

    # Days where a teacher is stacked up with no break
    day_warnings = []
    for t in active_teachers():
        tl = day_timeline(t.id, today)
        for w in tl["warnings"]:
            day_warnings.append({"teacher": t, "text": w})

    at_risk = students_at_risk(start, end)[:8]
    setup = [
        {"label": "Add teachers and their working hours", "done": counts["teachers"] > 0,
         "where": url_for("admin.teachers"),
         "why": "Hours and days off drive every scheduling decision."},
        {"label": "Create courses", "done": counts["courses"] > 0,
         "where": url_for("admin.courses"),
         "why": "One per subject. Both batch and one-to-one classes sit under it."},
        {"label": "Add students", "done": counts["students"] > 0,
         "where": url_for("admin.students"),
         "why": "Add them one at a time or paste a whole intake."},
        {"label": "Set up classes", "done": ClassGroup.query.count() > 0,
         "where": url_for("admin.class_new"),
         "why": "Pick the subject, the days and times, and who attends."},
    ]
    # classes whose timetable is about to run out
    expiring = expiring_classes()

    return render_template("admin/overview.html", expiring=expiring,
                           counts=counts, todays=todays, pending=pending[:10],
                           free=free, day_warnings=day_warnings,
                           at_risk=at_risk, setup=setup,
                           show_setup=any(not s["done"] for s in setup),
                           window_label=label, today=today,
                           students_list=User.query.filter_by(
                               role="STUDENT", status="ACTIVE")
                               .order_by(User.full_name).all(),
                           **_lists())


# ═══════════════════════════════════════════════════ STUDENTS ════════════

@bp.route("/admin/students")
@login_required
@admin_only
def students():
    f = _filters()
    start, end, label = window_from_request()
    query   = student_search(**f)
    page    = paginate(query, request.args.get("page", type=int))
    summaries = bulk_attendance_summary([s.id for s in page.items], start, end)
    dupe_names = [n for (n,) in
                  db.session.query(func.lower(User.full_name))
                  .filter_by(role="STUDENT")
                  .group_by(func.lower(User.full_name))
                  .having(func.count(User.id) > 1).all()]
    return render_template("admin/students.html",
                           page=page, filters=f, summaries=summaries,
                           window_label=label, dupe_count=len(dupe_names),
                           next_id=next_student_id(), **_lists())


@bp.route("/admin/students/new", methods=["POST"])
@login_required
@admin_only
def create_student():
    name = request.form.get("full_name", "").strip()
    if not name:
        flash("A name is required.", "danger")
        return redirect(url_for("admin.students"))
    existing = User.query.filter(
        User.role == "STUDENT",
        func.lower(User.full_name) == name.lower()).first()
    if existing and request.form.get("create_anyway") != "1":
        flash(f"{name} already exists (ID {existing.username}). "
              f"Tick 'create anyway' if this is a different person.", "danger")
        return redirect(url_for("admin.students", q=name))
    pw = make_password()
    uid = next_student_id()
    student = User(
        username=uid, full_name=name, role="STUDENT",
        phone=request.form.get("phone","").strip() or None,
        email=request.form.get("email","").strip() or None,
        branch=request.form.get("branch") or None,

        initial_password=pw,
    )
    student.set_password(pw)
    db.session.add(student)
    db.session.commit()
    flash(f"{name} added — ID {uid}, password {pw}", "success")
    return redirect(url_for("admin.students"))


@bp.route("/admin/students/bulk", methods=["POST"])
@login_required
@admin_only
def bulk_students():
    raw   = request.form.get("names", "")
    branch= request.form.get("branch") or None
    force = request.form.get("create_anyway") == "1"
    created, skipped = [], []
    for line in raw.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        name  = parts[0] if parts else ""
        phone = parts[1] if len(parts) > 1 else None
        if not name:
            continue
        existing = User.query.filter(
            User.role == "STUDENT",
            func.lower(User.full_name) == name.lower()).first()
        if existing and not force:
            skipped.append(name)
            continue
        pw  = make_password()
        uid = next_student_id()
        s   = User(username=uid, full_name=name, role="STUDENT",
                   phone=phone, branch=branch,
                   initial_password=pw)
        s.set_password(pw)
        db.session.add(s)
        db.session.flush()
        created.append((uid, name, pw))
    db.session.commit()
    if created:
        flash(f"{len(created)} student(s) created. Download logins CSV to share passwords.", "success")
    if skipped:
        flash(f"Skipped {len(skipped)} duplicate name(s): {', '.join(skipped)}", "warning")
    return redirect(url_for("admin.students"))


@bp.route("/admin/students/action", methods=["POST"])
@login_required
@admin_only
def students_action():
    action   = request.form.get("action")
    ids_raw  = request.form.getlist("user_ids")
    if not ids_raw:
        flash("No students selected.", "warning")
        return redirect(request.form.get("back") or url_for("admin.students"))
    ids = [int(i) for i in ids_raw]
    people = User.query.filter(User.id.in_(ids)).all()

    if action == "archive":
        for p in people:
            p.status = "ARCHIVED"
        db.session.commit()
        flash(f"Archived {len(people)} student(s).", "success")

    elif action == "restore":
        for p in people:
            p.status = "ACTIVE"
        db.session.commit()
        flash(f"Restored {len(people)} student(s).", "success")

    elif action == "reset":
        msgs = []
        for p in people:
            pw = make_password()
            p.set_password(pw)
            p.initial_password = pw
            msgs.append(f"{p.full_name}: {pw}")
        db.session.commit()
        flash("Passwords reset — " + " | ".join(msgs), "success")

    elif action == "delete":
        confirm = request.form.get("confirm", "")
        if confirm != "DELETE":
            flash("Type DELETE in the confirmation box to permanently delete.", "danger")
            return redirect(request.form.get("back") or url_for("admin.students"))
        for p in people:
            db.session.delete(p)
        db.session.commit()
        flash(f"Permanently deleted {len(people)} student(s).", "success")

    return redirect(request.form.get("back") or url_for("admin.students"))


@bp.route("/admin/students/<int:sid>")
@login_required
@admin_only
def student_profile(sid):
    student = db.session.get(User, sid)
    if not student or not student.is_student:
        abort(404)
    start, end, label = window_from_request()
    courses_enrolled = student_courses(sid)
    att_by_course = {
        c.id: attendance_summary(sid, c.id, start, end)
        for c in courses_enrolled
    }
    # batch as well as one-to-one — membership is what counts
    schedules = sorted(
        get_student_schedule(sid, start - timedelta(days=60), end + timedelta(days=120)),
        key=lambda x: (x.date, x.start_time), reverse=True)[:20]
    results = (Result.query
               .filter_by(student_id=sid)
               .join(Assessment)
               .order_by(Assessment.assigned_date.desc())
               .all())
    logs = (LessonLog.query
            .filter(LessonLog.course_id.in_([c.id for c in courses_enrolled]))
            .order_by(LessonLog.class_date.desc())
            .limit(20).all())
    consec = consecutive_absences(sid)
    lists = _lists()
    lists.pop("courses", None)
    return render_template("admin/student_profile.html",
                           student=student,
                           courses=courses_enrolled,
                           att=att_by_course,
                           schedules=schedules,
                           results=results,
                           logs=logs,
                           consec=consec,
                           window_label=label,
                           **lists)


@bp.route("/admin/students/<int:sid>/edit", methods=["GET","POST"])
@login_required
@admin_only
def edit_student(sid):
    student = db.session.get(User, sid)
    if not student or not student.is_student:
        abort(404)
    if request.method == "POST":
        student.full_name = request.form.get("full_name","").strip() or student.full_name
        student.phone     = request.form.get("phone","").strip() or None
        student.email     = request.form.get("email","").strip() or None
        student.branch    = request.form.get("branch") or None
        student.status    = request.form.get("status", student.status)
        new_pw = request.form.get("new_password","").strip()
        if new_pw:
            if len(new_pw) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return redirect(url_for("admin.edit_student", sid=sid))
            student.set_password(new_pw)
            student.initial_password = new_pw
        db.session.commit()
        flash(f"{student.full_name} updated.", "success")
        return redirect(url_for("admin.student_profile", sid=sid))
    return render_template("admin/edit_student.html", student=student, **_lists())


@bp.route("/admin/students/<int:sid>/delete", methods=["POST"])
@login_required
@admin_only
def delete_student(sid):
    student = db.session.get(User, sid)
    if not student:
        abort(404)
    confirm = request.form.get("confirm","")
    if confirm != "DELETE":
        flash("Type DELETE to confirm permanent deletion.", "danger")
        return redirect(url_for("admin.student_profile", sid=sid))
    name = student.full_name
    db.session.delete(student)
    db.session.commit()
    flash(f"{name} permanently deleted.", "success")
    log_action("student-delete", f"Student {sid} '{name}' DELETED")
    return redirect(url_for("admin.students"))


@bp.route("/admin/students/export.csv")
@login_required
@admin_only
def students_export():
    f = _filters()
    start, end, _ = window_from_request()
    people = student_search(**f).all()
    return students_csv(people, bulk_attendance_summary([p.id for p in people], start, end))


@bp.route("/admin/credentials.csv")
@login_required
@admin_only
def credentials_export():
    f = _filters()
    role = request.args.get("role","STUDENT")
    if role == "TEACHER":
        people = student_search(status=f["status"], role="TEACHER", q=f["q"]).all()
    else:
        people = student_search(**f).all()
    return credentials_csv(people)


# ═══════════════════════════════════════════════════ TEACHERS ════════════

@bp.route("/admin/teachers")
@login_required
@admin_only
def teachers():
    q = request.args.get("q","").strip()
    query = User.query.filter_by(role="TEACHER")
    if q:
        query = query.filter(User.full_name.ilike(f"%{q}%") | User.phone.ilike(f"%{q}%"))
    all_teachers = query.order_by(User.full_name).all()
    return render_template("admin/teachers.html", teachers=all_teachers, q=q)


def _read_availability(form):
    """Turn the seven-row availability grid into days_off + work_hours."""
    off, spans = [], []
    for wd in range(7):
        if form.get(f"works_{wd}") != "1":
            off.append(str(wd))
            continue
        a = (form.get(f"from_{wd}") or "10:00").strip()
        b = (form.get(f"to_{wd}") or "20:00").strip()
        try:
            ah, am = [int(x) for x in a.split(":")]
            bh, bm = [int(x) for x in b.split(":")]
            if (bh * 60 + bm) <= (ah * 60 + am):
                bh, bm = 20, 0
        except ValueError:
            ah, am, bh, bm = 10, 0, 20, 0
        spans.append(f"{wd}={ah:02d}:{am:02d}-{bh:02d}:{bm:02d}")
    return ",".join(off), ";".join(spans)


@bp.route("/admin/teachers/new", methods=["POST"])
@login_required
@admin_only
def create_teacher():
    name = request.form.get("full_name","").strip()
    if not name:
        flash("Name required.", "danger")
        return redirect(url_for("admin.teachers"))
    dupe = (User.query.filter_by(role="TEACHER")
            .filter(db.func.lower(User.full_name) == name.lower()).first())
    if dupe and request.form.get("create_anyway") != "1":
        flash(f"{name} is already on file (username {dupe.username}). "
              f"Tick 'add anyway' if this is a different person.", "danger")
        return redirect(url_for("admin.teachers"))
    username = unique_username(name)
    pw = make_password()
    teacher = User(
        username=username, full_name=name, role="TEACHER",
        phone=request.form.get("phone","").strip() or None,
        email=request.form.get("email","").strip() or None,
        branch=request.form.get("branch") or None,
        subjects=request.form.get("subjects","").strip() or None,
        max_daily_hours=float(request.form.get("max_daily_hours",8) or 8),
        initial_password=pw,
    )
    teacher.days_off, teacher.work_hours = _read_availability(request.form)
    teacher.set_password(pw)
    db.session.add(teacher)
    db.session.commit()
    flash(f"{name} added — username {username}, password {pw}", "success")
    return redirect(url_for("admin.teachers"))


@bp.route("/admin/teachers/<int:tid>/edit", methods=["GET","POST"])
@login_required
@admin_only
def edit_teacher(tid):
    teacher = db.session.get(User, tid)
    if not teacher or not teacher.is_teacher:
        abort(404)
    if request.method == "POST":
        teacher.full_name     = request.form.get("full_name","").strip() or teacher.full_name
        teacher.phone         = request.form.get("phone","").strip() or None
        teacher.email         = request.form.get("email","").strip() or None
        teacher.branch        = request.form.get("branch") or None
        teacher.subjects      = request.form.get("subjects","").strip() or None
        teacher.max_daily_hours = float(request.form.get("max_daily_hours",8) or 8)
        teacher.status        = request.form.get("status", teacher.status)
        if request.form.get("set_availability") == "1":
            teacher.days_off, teacher.work_hours = _read_availability(request.form)
        new_pw = request.form.get("new_password","").strip()
        if new_pw:
            teacher.set_password(new_pw)
            teacher.initial_password = new_pw
        db.session.commit()
        flash(f"{teacher.full_name} updated.", "success")
        return redirect(url_for("admin.teachers"))
    return render_template("admin/edit_teacher.html", teacher=teacher)


@bp.route("/admin/teachers/<int:tid>/delete", methods=["POST"])
@login_required
@admin_only
def delete_teacher(tid):
    teacher = db.session.get(User, tid)
    if not teacher:
        abort(404)
    upcoming = ClassSchedule.query.filter(
        ClassSchedule.teacher_id == tid,
        ClassSchedule.date >= date.today(),
        ClassSchedule.status == "Scheduled",
    ).count()
    if upcoming > 0:
        flash(f"Cannot delete — {teacher.full_name} has {upcoming} upcoming class(es). "
              f"Reassign or cancel them first.", "danger")
        return redirect(url_for("admin.teachers"))
    name = teacher.full_name
    db.session.delete(teacher)
    db.session.commit()
    flash(f"{name} deleted.", "success")
    return redirect(url_for("admin.teachers"))


# ═══════════════════════════════════════════════════ BATCHES ════════════

# ═══════════════════════════════════════════════════ COURSES ════════════

@bp.route("/admin/courses")
@login_required
@admin_only
def courses():
    show_archived = request.args.get("archived") == "1"
    q_courses = Course.query
    if not show_archived:
        q_courses = q_courses.filter_by(is_archived=False)
    all_courses = q_courses.order_by(Course.course_code).all()
    lists = _lists()
    lists.pop("courses", None)
    return render_template("admin/courses.html", courses=all_courses,
                           show_archived=show_archived, **lists)


@bp.route("/admin/courses/new", methods=["POST"])
@login_required
@admin_only
def create_course():
    code = request.form.get("course_code","").strip().upper()
    name = request.form.get("course_name","").strip()
    if not code or not name:
        flash("Course code and name required.", "danger")
        return redirect(url_for("admin.courses"))
    if Course.query.filter_by(course_code=code).first():
        flash(f"Course code {code} already exists.", "danger")
        return redirect(url_for("admin.courses"))
    c = Course(
        course_code=code,
        course_name=name,
        description=request.form.get("description","").strip() or None,
        branch=request.form.get("branch") or None,
    )
    db.session.add(c)
    db.session.commit()
    flash(f"{code} created.", "success")
    return redirect(url_for("admin.course_detail", cid=c.id))


@bp.route("/admin/courses/<int:cid>")
@login_required
@admin_only
def course_detail(cid):
    course = db.session.get(Course, cid)
    if not course:
        abort(404)
    assignments = (ClassAssignment.query.filter_by(course_id=cid)
                   .join(User, ClassAssignment.student_id == User.id)
                   .order_by(User.full_name).all())
    students_enrolled = [a.student for a in assignments]
    available_students = (User.query.filter_by(role="STUDENT", status="ACTIVE")
                          .filter(User.id.notin_([s.id for s in students_enrolled]))
                          .order_by(User.full_name).all())
    course_teacher = None
    _g = (ClassGroup.query.filter_by(course_id=cid, status="Active")
          .order_by(ClassGroup.id).first())
    if _g:
        course_teacher = _g.teacher
    return render_template("admin/course_detail.html",
                           course_classes=ClassGroup.query.filter_by(course_id=cid)
                               .order_by(ClassGroup.kind, ClassGroup.name).all(),
                           course_teacher=course_teacher,
                           course=course,
                           assignments=assignments,
                           available_students=available_students,
                           **_lists())


@bp.route("/admin/courses/<int:cid>/enrol", methods=["POST"])
@login_required
@admin_only
def enrol(cid):
    course = db.session.get(Course, cid)
    if not course:
        abort(404)
    tid     = request.form.get("teacher_id", type=int)
    mode    = request.form.get("mode","individual")
    created = 0
    if mode == "class":
        gid = request.form.get("group_id", type=int)
        g = db.session.get(ClassGroup, gid) if gid else None
        if not g:
            flash("Choose a class.", "danger")
            return redirect(url_for("admin.course_detail", cid=cid))
        students = [m.student for m in g.members if m.student]
    else:
        sids = request.form.getlist("student_ids")
        students = User.query.filter(User.id.in_([int(i) for i in sids])).all()

    # If a class already exists for this subject it carries the teacher, so
    # there is nothing to ask the administrator about.
    if not tid:
        g = (ClassGroup.query.filter_by(course_id=cid, status="Active")
             .order_by(ClassGroup.id).first())
        if g:
            tid = g.teacher_id
        else:
            flash("This subject has no class yet, so choose who teaches it.",
                  "danger")
            return redirect(url_for("admin.course_detail", cid=cid))

    for s in students:
        existing = ClassAssignment.query.filter_by(
            course_id=cid, student_id=s.id).first()
        if not existing:
            db.session.add(ClassAssignment(
                course_id=cid, teacher_id=tid, student_id=s.id))
            created += 1
    db.session.commit()
    flash(f"{created} student(s) enrolled.", "success")
    return redirect(url_for("admin.course_detail", cid=cid))


@bp.route("/admin/courses/<int:cid>/unenrol", methods=["POST"])
@login_required
@admin_only
def unenrol(cid):
    sid = request.form.get("student_id", type=int)
    a   = ClassAssignment.query.filter_by(course_id=cid, student_id=sid).first()
    if a:
        db.session.delete(a)
        db.session.commit()
        flash("Student removed from course.", "success")
    return redirect(url_for("admin.course_detail", cid=cid))


@bp.route("/admin/courses/<int:cid>/edit", methods=["GET", "POST"])
@login_required
@admin_only
def edit_course(cid):
    """Rename a subject and write its description."""
    c = db.session.get(Course, cid)
    if not c:
        abort(404)

    if request.method == "POST":
        code = request.form.get("course_code", "").strip().upper()
        name = request.form.get("course_name", "").strip()
        if not code or not name:
            flash("A subject needs a code and a name.", "danger")
            return redirect(url_for("admin.edit_course", cid=cid))
        clash = (Course.query.filter(Course.course_code == code,
                                     Course.id != cid).first())
        if clash:
            flash(f"{code} is already used by '{clash.course_name}'.", "danger")
            return redirect(url_for("admin.edit_course", cid=cid))

        old_code = c.course_code
        c.course_code    = code
        c.course_name    = name
        c.description    = request.form.get("description", "").strip() or None
        c.mnemonic       = request.form.get("mnemonic", "").strip() or None
        c.awarding_body  = request.form.get("awarding_body", "").strip() or None
        c.level          = request.form.get("level", "").strip() or None
        c.credits        = request.form.get("credits", type=int)
        c.learning_hours = request.form.get("learning_hours", type=int)
        c.assessment     = request.form.get("assessment", "").strip() or None
        c.outcomes       = request.form.get("outcomes", "").strip() or None
        c.branch         = request.form.get("branch", "").strip() or None
        db.session.commit()
        log_action("course-edit", f"Course {cid}: {old_code} -> {code}")
        flash(f"'{name}' saved."
              + (f" The code changed from {old_code} to {code}, so it will read "
                 f"differently on routines and registers." if old_code != code else ""),
              "success")
        return redirect(url_for("admin.course_detail", cid=cid))

    groups = ClassGroup.query.filter_by(course_id=cid).all()
    return render_template("admin/course_edit.html", course=c, groups=groups,
                           **_lists())


@bp.route("/admin/courses/<int:cid>/archive", methods=["POST"])
@login_required
@admin_only
def archive_course(cid):
    course = db.session.get(Course, cid)
    if not course:
        abort(404)
    course.is_archived = not course.is_archived
    db.session.commit()
    flash(f"Course {'archived' if course.is_archived else 'restored'}.", "success")
    return redirect(url_for("admin.courses"))


@bp.route("/admin/courses/<int:cid>/delete", methods=["POST"])
@login_required
@admin_only
def delete_course(cid):
    course = db.session.get(Course, cid)
    if not course:
        abort(404)
    confirm = request.form.get("confirm","")
    if confirm != "DELETE":
        flash("Type DELETE to confirm.", "danger")
        return redirect(url_for("admin.course_detail", cid=cid))
    nm = course.course_name
    db.session.delete(course)
    db.session.commit()
    flash("Course permanently deleted.", "success")
    log_action("course-delete", f"Subject {cid} '{nm}' DELETED")
    return redirect(url_for("admin.courses"))


# ═══════════════════════════════════════════════════ SCHEDULE ════════════

@bp.route("/admin/schedule")
@login_required
@admin_only
def calendar():
    """Day, week or month — the layout follows the choice."""
    view   = request.args.get("view", "week")
    anchor = parse_date(request.args.get("date")) or date.today()
    tid    = request.args.get("teacher_id", type=int)
    today  = date.today()

    if view == "day":
        start = end = anchor
    elif view == "month":
        start = anchor.replace(day=1)
        nxt   = (start + timedelta(days=32)).replace(day=1)
        end   = nxt - timedelta(days=1)
    else:
        view  = "week"
        start = anchor - timedelta(days=anchor.weekday())
        end   = start + timedelta(days=6)

    q = ClassSchedule.query.filter(ClassSchedule.date >= start,
                                   ClassSchedule.date <= end)
    if tid:
        q = q.filter_by(teacher_id=tid)
    rows = q.order_by(ClassSchedule.date, ClassSchedule.start_time).all()

    days = {}
    d = start
    while d <= end:
        days[d] = []
        d += timedelta(days=1)
    for r in rows:
        if r.date in days:
            days[r.date].append(r)

    timelines = []
    if view == "day":
        pool = ([db.session.get(User, tid)] if tid else active_teachers())
        for t in pool:
            if t:
                timelines.append({"teacher": t, "tl": day_timeline(t.id, anchor)})

    step = {"day": timedelta(days=1), "week": timedelta(days=7),
            "month": timedelta(days=31)}[view]
    prev_d = (start - timedelta(days=1)) if view == "month" else (anchor - step)
    next_d = (end + timedelta(days=1)) if view == "month" else (anchor + step)

    return render_template("admin/calendar.html",
                           view=view, days=days, start=start, end=end,
                           anchor=anchor, prev_d=prev_d, next_d=next_d,
                           filter_tid=tid, today=today, timelines=timelines,
                           total=len(rows), **_lists())


@bp.route("/admin/schedule/<int:cid>/edit", methods=["GET", "POST"])
@login_required
@admin_only
def edit_schedule(cid):
    """Change one session without touching the rest of its run."""
    from datetime import time as dtime
    cls = db.session.get(ClassSchedule, cid)
    if not cls:
        abort(404)
    sids = ([cls.student_id] if cls.student_id else
            ([m.student_id for m in cls.group.members] if cls.group else []))

    if request.method == "POST":
        nd = parse_date(request.form.get("date")) or cls.date
        try:
            st = dtime(*[int(x) for x in request.form.get("start_time", "").split(":")[:2]])
            en = dtime(*[int(x) for x in request.form.get("end_time", "").split(":")[:2]])
        except (ValueError, TypeError):
            flash("Give a valid start and finish time.", "danger")
            return redirect(url_for("admin.edit_schedule", cid=cid))
        ntid = request.form.get("teacher_id", type=int) or cls.teacher_id
        v = check_slot(ntid, nd, st, en, sids, exclude_id=cid)

        if v["status"] != "ok" and not request.form.get("force"):
            dur = mins(en) - mins(st)
            options = suggest_times(ntid, nd, dur, sids, wanted=st,
                                    exclude_id=cid, limit=4)
            return render_template("admin/schedule_edit.html", cls=cls,
                                   verdict=v, options=options, **_lists())

        cls.date, cls.start_time, cls.end_time = nd, st, en
        cls.duration_mins = mins(en) - mins(st)
        cls.teacher_id = ntid
        cls.task   = request.form.get("task", cls.task)
        cls.venue  = request.form.get("venue", cls.venue)
        cls.status = request.form.get("status", cls.status)
        cls.notes  = request.form.get("notes", cls.notes)
        db.session.commit()
        flash("Class updated.", "success")
        return redirect(url_for("admin.calendar", view="day",
                                date=cls.date.isoformat()))

    return render_template("admin/schedule_edit.html", cls=cls,
                           verdict=None, options=[], **_lists())


@bp.route("/admin/schedule/<int:cid>/cancel", methods=["POST"])
@login_required
@admin_only
def cancel_schedule(cid):
    cls = db.session.get(ClassSchedule, cid)
    if not cls:
        abort(404)
    cls.status = "Cancelled"
    db.session.commit()
    flash("Class cancelled. The slot is free again.", "info")
    return redirect(request.referrer or url_for("admin.calendar"))


@bp.route("/admin/schedule/<int:cid>/delete", methods=["POST"])
@login_required
@admin_only
def delete_schedule(cid):
    cls = db.session.get(ClassSchedule, cid)
    if not cls:
        abort(404)
    d = cls.date
    db.session.delete(cls)
    db.session.commit()
    flash("Class removed.", "success")
    return redirect(url_for("admin.calendar", view="day", date=d.isoformat()))


@bp.route("/admin/schedule/quick-add", methods=["POST"])
@login_required
@admin_only
def quick_add():
    """Fill a free gap straight from the dashboard or the day view."""
    from datetime import time as dtime
    tid = request.form.get("teacher_id", type=int)
    d   = parse_date(request.form.get("date")) or date.today()
    try:
        st = dtime(*[int(x) for x in request.form.get("start_time", "").split(":")[:2]])
        en = dtime(*[int(x) for x in request.form.get("end_time", "").split(":")[:2]])
    except (ValueError, TypeError):
        flash("Give a valid time.", "danger")
        return redirect(request.referrer or url_for("admin.overview"))

    what = request.form.get("what", "class")
    sid  = request.form.get("student_id", type=int) or None
    task = request.form.get("task", "").strip()

    if what == "break":
        db.session.add(TeacherBlock(
            teacher_id=tid, label=task or "Break",
            weekday=None, start_time=st, end_time=en, on_date=d))
        db.session.commit()
        flash(f"'{task or 'Break'}' kept clear on {d.strftime('%a %d %b')}.",
              "success")
        return redirect(request.referrer or url_for("admin.overview"))

    v = check_slot(tid, d, st, en, [sid] if sid else [])
    if v["status"] == "clash" and not request.form.get("force"):
        flash(f"Cannot book: {v['message']}", "danger")
        return redirect(request.referrer or url_for("admin.overview"))

    if not task:
        who = db.session.get(User, sid) if sid else None
        task = f"{who.full_name} 1-1" if who else "Class"
    db.session.add(ClassSchedule(
        date=d, start_time=st, end_time=en, duration_mins=mins(en) - mins(st),
        task=task, class_type="1-on-1" if sid else "Batch",
        venue=request.form.get("venue", "Centre"),
        teacher_id=tid, student_id=sid,
        course_id=request.form.get("course_id", type=int) or None,
        status="Scheduled", created_by=current_user.id))
    db.session.commit()
    flash(f"'{task}' booked for {d.strftime('%a %d %b')} at {fmt(st)}.", "success")
    return redirect(request.referrer or url_for("admin.overview"))


@bp.route("/admin/schedule/export.csv")
@login_required
@admin_only
def schedule_export():
    # Default: this month through three months ahead, so upcoming classes are included.
    today = date.today()
    default_start = today.replace(day=1)
    default_end   = today + timedelta(days=120)
    start = parse_date(request.args.get("start")) or default_start
    end   = parse_date(request.args.get("end"))   or default_end
    tid   = request.args.get("teacher_id", type=int)
    q = ClassSchedule.query.filter(
        ClassSchedule.date >= start,
        ClassSchedule.date <= end,
    )
    if tid:
        q = q.filter_by(teacher_id=tid)
    return schedule_csv(q.order_by(ClassSchedule.date, ClassSchedule.start_time).all())


# ═══════════════════════════════════════════════════ PDF EXPORTS ══════════

def _pdf(data, filename):
    from flask import Response
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def _no_pdf():
    flash("PDF export needs the fpdf2 package. Run: pip install fpdf2", "danger")
    return redirect(request.referrer or url_for("admin.calendar"))


@bp.route("/admin/routines", methods=["GET"])
@login_required
@admin_only
def routines():
    """One place to produce any routine as a PDF."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return render_template("admin/routines.html",
                           week_start=monday,
                           week_end=monday + timedelta(days=6),
                           next_week_start=monday + timedelta(days=7),
                           next_week_end=monday + timedelta(days=13),
                           month_start=today.replace(day=1),
                           month_end=(today.replace(day=28) + timedelta(days=4)
                                      ).replace(day=1) - timedelta(days=1),
                           students=User.query.filter_by(role="STUDENT",
                                                         status="ACTIVE")
                                     .order_by(User.full_name).all(),
                           **_lists())


@bp.route("/admin/routines/generate")
@login_required
@admin_only
def routines_generate():
    """Build whichever routine was asked for."""
    who   = request.args.get("who", "all_students")
    start = parse_date(request.args.get("start")) or date.today()
    end   = parse_date(request.args.get("end")) or (start + timedelta(days=30))
    note  = ("Please arrive five minutes early. Tell the office as soon as "
             "possible if you cannot attend a class.")

    try:
        from pdf_export import (students_routines_pdf, student_routine_pdf,
                                teachers_schedules_pdf, teacher_schedule_pdf,
                                weekly_schedule_pdf, batch_timetable_pdf)
    except Exception:
        return _no_pdf()

    def teacher_rows(tid):
        return (ClassSchedule.query
                .filter(ClassSchedule.teacher_id == tid,
                        ClassSchedule.date >= start, ClassSchedule.date <= end)
                .order_by(ClassSchedule.date, ClassSchedule.start_time).all())

    def student_bundle(people):
        out = []
        for p in people:
            c, r = _student_record(p.id, start, end)
            out.append((p, _student_sessions(p.id, start, end), c, r))
        return out

    try:
        if who == "all_teachers":
            staff = (User.query.filter_by(role="TEACHER", status="ACTIVE")
                     .order_by(User.full_name).all())
            data = teachers_schedules_pdf([(t, teacher_rows(t.id)) for t in staff],
                                          start, end)
            return _pdf(data, f"teacher_timetables_{start.isoformat()}.pdf")

        if who == "teacher":
            tid = request.args.get("teacher_id", type=int)
            t = db.session.get(User, tid) if tid else None
            if not t:
                flash("Choose a teacher.", "danger")
                return redirect(url_for("admin.routines"))
            data = teacher_schedule_pdf(t, teacher_rows(t.id), start, end)
            return _pdf(data, f"timetable_{t.full_name.replace(' ', '_')}.pdf")

        if who == "all_students":
            people = (User.query.filter_by(role="STUDENT", status="ACTIVE")
                      .order_by(User.full_name).all())
            data = students_routines_pdf(student_bundle(people), start, end, note)
            return _pdf(data, f"student_routines_{start.isoformat()}.pdf")

        if who == "student":
            sid = request.args.get("student_id", type=int)
            s = db.session.get(User, sid) if sid else None
            if not s:
                flash("Choose a student.", "danger")
                return redirect(url_for("admin.routines"))
            c, r = _student_record(s.id, start, end)
            data = student_routine_pdf(s, _student_sessions(s.id, start, end),
                                       start, end, note, c, r)
            return _pdf(data, f"routine_{s.username}.pdf")


        if who == "course":
            cid = request.args.get("course_id", type=int)
            c_obj = db.session.get(Course, cid) if cid else None
            if not c_obj:
                flash("Choose a course.", "danger")
                return redirect(url_for("admin.routines"))
            ids = [a.student_id for a in
                   ClassAssignment.query.filter_by(course_id=cid).all()]
            people = (User.query.filter(User.id.in_(ids))
                      .order_by(User.full_name).all())
            data = students_routines_pdf(student_bundle(people), start, end, note)
            return _pdf(data, f"routines_{c_obj.course_code}.pdf")

        if who == "centre":
            rows = (ClassSchedule.query
                    .filter(ClassSchedule.date >= start, ClassSchedule.date <= end)
                    .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
            data = weekly_schedule_pdf(rows, start, end)
            return _pdf(data, f"centre_schedule_{start.isoformat()}.pdf")

        if who == "batch_timetable":
            rows = (ClassSchedule.query.filter_by(class_type="Batch")
                    .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
            data = batch_timetable_pdf(rows)
            return _pdf(data, "batch_timetable.pdf")

    except RuntimeError:
        return _no_pdf()

    flash("Choose what to produce.", "danger")
    return redirect(url_for("admin.routines"))


@bp.route("/admin/schedule/export.pdf")
@login_required
@admin_only
def schedule_pdf():
    """Whole schedule for a date range, one block per day."""
    try:
        from pdf_export import weekly_schedule_pdf
    except Exception:
        return _no_pdf()

    today = date.today()
    start = parse_date(request.args.get("start")) or today.replace(day=1)
    end   = parse_date(request.args.get("end"))   or today + timedelta(days=30)
    tid   = request.args.get("teacher_id", type=int)

    q = ClassSchedule.query.filter(ClassSchedule.date >= start,
                                   ClassSchedule.date <= end)
    who = None
    if tid:
        q = q.filter_by(teacher_id=tid)
        t = db.session.get(User, tid)
        who = t.full_name if t else None
    rows = q.order_by(ClassSchedule.date, ClassSchedule.start_time).all()
    try:
        data = weekly_schedule_pdf(rows, start, end, who)
    except RuntimeError:
        return _no_pdf()
    return _pdf(data, f"schedule_{start.isoformat()}_{end.isoformat()}.pdf")


@bp.route("/admin/schedule/batches.pdf")
@login_required
@admin_only
def batch_timetable_pdf_route():
    """Every batch class, grouped by slot."""
    try:
        from pdf_export import batch_timetable_pdf
    except Exception:
        return _no_pdf()
    rows = (ClassSchedule.query.filter_by(class_type="Batch")
            .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
    try:
        data = batch_timetable_pdf(rows)
    except RuntimeError:
        return _no_pdf()
    return _pdf(data, "batch_timetable.pdf")


def _student_sessions(sid, start, end):
    """Group membership and direct assignment only — never course-wide."""
    return get_student_schedule(sid, start, end)


def _routine_window():
    today = date.today()
    start = parse_date(request.args.get("start")) or today
    end   = parse_date(request.args.get("end")) or (start + timedelta(days=30))
    return start, end


def _student_record(sid, win_start, win_end):
    """Courses with attendance, plus marks — the same figures as the profile page."""
    term_start, term_end, _ = window_from_request()
    courses = []
    for a in ClassAssignment.query.filter_by(student_id=sid).all():
        summary = attendance_summary(sid, a.course_id, term_start, term_end)
        courses.append({"code": a.course.course_code,
                        "name": a.course.course_name,
                        "att": summary})
    courses.sort(key=lambda c: c["code"])

    results = []
    for r in (Result.query.filter_by(student_id=sid)
              .join(Assessment).order_by(Assessment.assigned_date.desc()).all()):
        a = r.assessment
        results.append({
            "title": a.title, "course": a.course.course_code,
            "kind": a.kind, "state": r.state,
            "score": (f"{r.score:g}/{a.max_score:g}"
                      if r.score is not None else "-"),
        })
    return courses, results


@bp.route("/admin/students/<int:sid>/routine.pdf")
@login_required
@admin_only
def student_routine_pdf_route(sid):
    """One student's routine, ready to hand over."""
    try:
        from pdf_export import student_routine_pdf
    except Exception:
        return _no_pdf()
    student = db.session.get(User, sid)
    if not student or not student.is_student:
        abort(404)
    start, end = _routine_window()
    rows = _student_sessions(sid, start, end)
    courses, results = _student_record(sid, start, end)
    note = ("Please arrive five minutes early. Tell the office as soon as "
            "possible if you cannot attend a class.")
    try:
        data = student_routine_pdf(student, rows, start, end, note,
                                   courses, results)
    except RuntimeError:
        return _no_pdf()
    safe = student.full_name.replace(" ", "_").replace(",", "")
    return _pdf(data, f"routine_{student.username}_{safe}.pdf")


@bp.route("/admin/students/routines.pdf")
@login_required
@admin_only
def student_routines_pdf_route():
    """Every student on the current filter, one page each."""
    try:
        from pdf_export import students_routines_pdf
    except Exception:
        return _no_pdf()
    f = _filters()
    people = student_search(**f).all()
    start, end = _routine_window()
    items = []
    for p in people:
        c, r = _student_record(p.id, start, end)
        items.append((p, _student_sessions(p.id, start, end), c, r))
    note = ("Please arrive five minutes early. Tell the office as soon as "
            "possible if you cannot attend a class.")
    try:
        data = students_routines_pdf(items, start, end, note)
    except RuntimeError:
        return _no_pdf()
    return _pdf(data, f"routines_{start.isoformat()}.pdf")


@bp.route("/admin/teachers/<int:tid>/schedule.pdf")
@login_required
@admin_only
def teacher_pdf(tid):
    """One teacher's personal timetable."""
    try:
        from pdf_export import teacher_schedule_pdf
    except Exception:
        return _no_pdf()
    teacher = db.session.get(User, tid)
    if not teacher:
        abort(404)
    today = date.today()
    start = parse_date(request.args.get("start")) or today - timedelta(days=today.weekday())
    end   = parse_date(request.args.get("end"))   or start + timedelta(days=6)
    rows = (ClassSchedule.query.filter(ClassSchedule.teacher_id == tid,
                                       ClassSchedule.date >= start,
                                       ClassSchedule.date <= end)
            .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
    try:
        data = teacher_schedule_pdf(teacher, rows, start, end)
    except RuntimeError:
        return _no_pdf()
    safe = teacher.full_name.replace(" ", "_")
    return _pdf(data, f"timetable_{safe}_{start.isoformat()}.pdf")


# ═══════════════════════════════════════════════════ TERMS ════════════

@bp.route("/admin/terms")
@login_required
@admin_only
def terms():
    """Terms set the window attendance percentages are measured over."""
    lists = _lists()
    lists.pop("terms", None)
    return render_template("admin/terms.html",
                           terms=Term.query.order_by(Term.start_date.desc()).all(),
                           **lists)


@bp.route("/admin/terms/new", methods=["POST"])
@login_required
@admin_only
def create_term():
    name  = request.form.get("name","").strip()
    start = parse_date(request.form.get("start_date"))
    end   = parse_date(request.form.get("end_date"))
    if not name or not start or not end:
        flash("Name, start and end dates required.", "danger")
        return redirect(url_for("admin.terms"))
    t = Term(name=name, start_date=start, end_date=end)
    db.session.add(t)
    db.session.commit()
    flash(f"Term '{name}' created.", "success")
    return redirect(url_for("admin.terms"))


@bp.route("/admin/terms/<int:tid>/set-current", methods=["POST"])
@login_required
@admin_only
def set_current_term(tid):
    Term.query.update({"is_current": False})
    t = db.session.get(Term, tid)
    if t:
        t.is_current = True
    db.session.commit()
    flash(f"'{t.name}' is now the current term.", "success")
    return redirect(url_for("admin.terms"))


# ═══════════════════════════════════════════════════ CLASSES ══════════════

def _slots_from_form(form):
    """Read the repeating slot rows off the create/edit form."""
    from datetime import time as dtime
    out = []
    for key in form.keys():
        if not key.startswith("slot_day_"):
            continue
        idx = key.split("_")[-1]
        wd = form.get(f"slot_day_{idx}")
        a  = form.get(f"slot_from_{idx}", "")
        b  = form.get(f"slot_to_{idx}", "")
        if wd is None or wd == "" or not a or not b:
            continue
        try:
            st = dtime(*[int(x) for x in a.split(":")[:2]])
            en = dtime(*[int(x) for x in b.split(":")[:2]])
        except (ValueError, TypeError):
            continue
        if en <= st:
            continue
        out.append((int(wd), st, en))
    return out


@bp.route("/admin/classes")
@login_required
@admin_only
def classes():
    kind   = request.args.get("kind", "")
    status = request.args.get("status", "")
    cid    = request.args.get("course_id", type=int)
    q = ClassGroup.query
    if kind:
        q = q.filter_by(kind=kind)
    if status:
        q = q.filter_by(status=status)
    if cid:
        q = q.filter_by(course_id=cid)
    groups = q.order_by(ClassGroup.status, ClassGroup.name).all()
    if request.args.get("expiring"):
        soon = {e["group"].id for e in expiring_classes()}
        groups = [g for g in groups if g.id in soon]
    rows = [{"g": g, "c": g.counts()} for g in groups]
    totals = {
        "batch":   ClassGroup.query.filter_by(kind="Batch").count(),
        "one":     ClassGroup.query.filter_by(kind="1-on-1").count(),
        "active":  ClassGroup.query.filter_by(status="Active").count(),
        "paused":  ClassGroup.query.filter_by(status="Paused").count(),
        "stopped": ClassGroup.query.filter_by(status="Stopped").count(),
    }
    return render_template("admin/classes.html", rows=rows, totals=totals,
                           kind=kind, status=status, course_id=cid, **_lists())


@bp.route("/admin/classes/new", methods=["GET", "POST"])
@login_required
@admin_only
def class_new():
    if request.method == "POST":
        kind  = request.form.get("kind", "Batch")
        tid   = request.form.get("teacher_id", type=int)
        cid   = request.form.get("course_id", type=int) or None
        name  = request.form.get("name", "").strip()
        venue = request.form.get("venue", "Centre")
        sids  = [int(x) for x in request.form.getlist("student_ids")]
        start = parse_date(request.form.get("start_date")) or date.today()
        runs  = request.form.get("runs", "forever")
        slots = _slots_from_form(request.form)
        forever = runs == "forever"
        end = None
        want = None
        if runs == "count":
            want = request.form.get("num_classes", type=int)
            if not want or want < 1:
                flash("How many classes? Give a number of 1 or more.", "danger")
                return redirect(url_for("admin.class_new"))
            # Build with headroom, then trim to exactly `want`. Headroom
            # matters because days off, breaks and clashes all drop dates,
            # so a naive week count comes up short.
            days = {wd for wd, _, _ in slots}
            end = date_for_count(days, start, want * 3, tid) if days else None
        elif runs == "until":
            end = parse_date(request.form.get("end_date"))

        course = db.session.get(Course, cid) if cid else None
        if not tid:
            flash("Choose a teacher.", "danger")
            return redirect(url_for("admin.class_new"))
        if not slots:
            flash("Add at least one day and time.", "danger")
            return redirect(url_for("admin.class_new"))
        if runs == "until" and not end:
            flash("Give a finish date, or choose one of the other options.",
                  "danger")
            return redirect(url_for("admin.class_new"))
        if not name:
            if kind == "1-on-1" and sids:
                who = db.session.get(User, sids[0])
                name = f"{who.full_name} - {course.course_name if course else 'class'}"
            elif course:
                name = course.course_name
            else:
                flash("Give the class a name.", "danger")
                return redirect(url_for("admin.class_new"))

        # ── Check the pattern BEFORE creating anything ──────────────────────
        if request.form.get("resolved") != "1":
            problems = []
            for i, (wd, st, en) in enumerate(slots):
                res = analyse_slot(tid, wd, st, en, sids, start, end)
                if res["clean"]:
                    continue
                opts = slot_options(tid, res["sample"], st, en, sids)
                problems.append({
                    "index": i, "weekday": wd, "start": st, "end": en,
                    "res": res, "opts": opts,
                })
            if problems:
                payload = {
                    "kind": kind, "teacher_id": tid, "course_id": cid,
                    "name": name, "venue": venue, "student_ids": sids,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat() if end else "",
                    "runs": runs,
                    "slots": [[wd, st.strftime("%H:%M"), en.strftime("%H:%M")]
                              for wd, st, en in slots],
                }
                return render_template("admin/class_resolve.html",
                                       problems=problems, payload=payload,
                                       payload_json=json.dumps(payload),
                                       teacher=db.session.get(User, tid),
                                       course=course, name=name,
                                       slots=slots, **_lists())

        g = ClassGroup(name=name, kind=kind, course_id=cid, teacher_id=tid,
                       venue=venue, start_date=start, end_date=end,
                       status="Active")
        db.session.add(g)
        db.session.flush()
        for wd, st, en in slots:
            db.session.add(ClassSlot(group_id=g.id, weekday=wd,
                                     start_time=st, end_time=en))
        for sid in sids:
            db.session.add(GroupStudent(group_id=g.id, student_id=sid))
            if cid and not ClassAssignment.query.filter_by(
                    course_id=cid, student_id=sid).first():
                db.session.add(ClassAssignment(course_id=cid, teacher_id=tid,
                                               student_id=sid))
        db.session.flush()
        res = generate_group(g)

        if want:
            extra = (g.sessions.filter(ClassSchedule.status == "Scheduled")
                     .order_by(ClassSchedule.date.desc(),
                               ClassSchedule.start_time.desc()).all())[:-want or None]
            for x in extra:
                db.session.delete(x)
            kept = g.sessions.filter(ClassSchedule.status == "Scheduled").all()
            if kept:
                g.end_date = max(x.date for x in kept)
                g.generated_to = g.end_date
            db.session.commit()
            res["made"] = len(kept)

        msg = f"'{name}' created. {res['made']} class(es) booked"
        if res["clash"] or res["off"]:
            msg += (f", {res['clash'] + res['off']} date(s) could not be used — "
                    f"open the class to see which")
        flash(msg + ".", "success" if res["made"] else "warning")
        return redirect(url_for("admin.class_detail", gid=g.id))

    return render_template("admin/class_new.html",
                           students=User.query.filter_by(role="STUDENT",
                                                         status="ACTIVE")
                                     .order_by(User.full_name).all(),
                           **_lists())


@bp.route("/admin/classes/create", methods=["POST"])
@login_required
@admin_only
def class_create_resolved():
    """Second pass: the admin has chosen how to handle each clash."""
    try:
        payload = json.loads(request.form.get("payload", "{}"))
    except ValueError:
        flash("Something went wrong. Please set the class up again.", "danger")
        return redirect(url_for("admin.class_new"))

    tid   = payload.get("teacher_id")
    slots = payload.get("slots", [])
    keep  = []

    for i, (wd, a, b) in enumerate(slots):
        choice = request.form.get(f"fix_{i}", "keep")
        if choice == "skip":
            continue
        if choice.startswith("time:"):
            span = choice[5:]
            if "-" not in span:
                continue
            na, nb = span.split("-", 1)
            keep.append([int(wd), na.strip(), nb.strip(), tid])
        elif choice.startswith("teacher:"):
            keep.append([int(wd), a, b, int(choice.split(":")[1])])
        else:
            keep.append([int(wd), a, b, tid])

    if not keep:
        flash("Every day was skipped, so nothing was created.", "warning")
        return redirect(url_for("admin.class_new"))

    # A different teacher on some days means a class each — keep it honest
    from datetime import time as dtime
    by_teacher = {}
    for wd, a, b, t in keep:
        by_teacher.setdefault(t, []).append((wd, a, b))

    made_groups, total = [], 0
    start = parse_date(payload.get("start_date")) or date.today()
    end   = parse_date(payload.get("end_date")) or None
    cid   = payload.get("course_id")
    sids  = payload.get("student_ids", [])

    for t, rows in by_teacher.items():
        label = payload["name"]
        if len(by_teacher) > 1:
            who = db.session.get(User, t)
            label = f"{payload['name']} ({who.full_name.split()[0]})"
        g = ClassGroup(name=label, kind=payload.get("kind", "Batch"),
                       course_id=cid, teacher_id=t,
                       venue=payload.get("venue", "Centre"),
                       start_date=start, end_date=end, status="Active")
        db.session.add(g)
        db.session.flush()
        for wd, a, b in rows:
            db.session.add(ClassSlot(
                group_id=g.id, weekday=wd,
                start_time=dtime(*[int(x) for x in a.split(":")]),
                end_time=dtime(*[int(x) for x in b.split(":")])))
        for sid in sids:
            db.session.add(GroupStudent(group_id=g.id, student_id=sid))
            if cid and not ClassAssignment.query.filter_by(
                    course_id=cid, student_id=sid).first():
                db.session.add(ClassAssignment(course_id=cid, teacher_id=t,
                                               student_id=sid))
        db.session.flush()
        r = generate_group(g)
        total += r["made"]
        made_groups.append(g)

    skipped = len(slots) - len(keep)
    msg = f"{total} class(es) booked"
    if len(made_groups) > 1:
        msg += f" across {len(made_groups)} class records (different teachers)"
    if skipped:
        msg += f", {skipped} day(s) skipped as you chose"
    flash(msg + ".", "success" if total else "warning")
    return redirect(url_for("admin.class_detail", gid=made_groups[0].id))


@bp.route("/admin/classes/<int:gid>")
@login_required
@admin_only
def class_detail(gid):
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    today = date.today()
    upcoming = (g.sessions.filter(ClassSchedule.date >= today)
                .order_by(ClassSchedule.date).limit(60).all())
    past = (g.sessions.filter(ClassSchedule.date < today)
            .order_by(ClassSchedule.date.desc()).limit(30).all())
    enrolled_ids = {m.student_id for m in g.members}
    available = (User.query.filter_by(role="STUDENT", status="ACTIVE")
                 .filter(User.id.notin_(enrolled_ids) if enrolled_ids else True)
                 .order_by(User.full_name).all())
    return render_template("admin/class_detail.html", g=g, c=g.counts(),
                           upcoming=upcoming, past=past,
                           available=available, **_lists())


@bp.route("/admin/classes/<int:gid>/slots", methods=["POST"])
@login_required
@admin_only
def class_slots(gid):
    """
    Change the weekly pattern, the teacher or the venue.

    Nothing is deleted until the replacement is known to work. Every proposed
    slot is checked against the chosen teacher first; if any of them will not
    fit, the existing timetable is left exactly as it is and the options are
    put to the administrator instead.
    """
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    slots = _slots_from_form(request.form)
    if not slots:
        flash("Keep at least one day and time.", "danger")
        return redirect(url_for("admin.class_detail", gid=gid))

    new_tid = request.form.get("teacher_id", type=int) or g.teacher_id
    venue   = request.form.get("venue", g.venue)
    new_name = request.form.get("name", "").strip()
    scope   = request.form.get("scope", "future")
    forced  = request.form.get("force") == "1"
    from_d  = date.today() if scope == "future" else g.start_date
    sids    = [m.student_id for m in g.members]

    # If nothing about the timetable actually changed, there is nothing to
    # check and nothing to rebuild. Renaming a class, or correcting its venue,
    # should not be pushed through a clash screen about times it already runs.
    current = sorted((sl.weekday, sl.start_time, sl.end_time) for sl in g.slots)
    unchanged = (sorted(slots) == current and new_tid == g.teacher_id)
    if unchanged:
        changed = []
        if new_name and new_name != g.name:
            old_name = g.name
            g.name = new_name[:160]
            for x in g.sessions.filter(ClassSchedule.date >= date.today()).all():
                x.task = g.name
            changed.append(f"renamed from '{old_name}'")
        if venue != g.venue:
            g.venue = venue
            changed.append(f"venue set to {venue}")
        db.session.commit()
        if changed:
            log_action("class-amend", f"Class {g.id}: {', '.join(changed)}")
            flash(f"'{g.name}' saved — {', and '.join(changed)}. "
                  f"The timetable was not touched.", "success")
        else:
            flash("Nothing to change.", "info")
        return redirect(url_for("admin.class_detail", gid=gid))

    # ── check first, change second ──────────────────────────────────────
    problems = []
    for i, (wd, st, en) in enumerate(slots):
        res = analyse_slot(new_tid, wd, st, en, sids, max(from_d, date.today()),
                           g.end_date, exclude_group_id=g.id)
        if res["clean"]:
            continue
        opts = slot_options(new_tid, res["sample"], st, en, sids)
        problems.append({"index": i, "weekday": wd, "start": st, "end": en,
                         "res": res, "opts": opts})

    if problems and not forced:
        counts = g.counts()
        return render_template(
            "admin/class_amend_resolve.html", g=g, problems=problems,
            teacher=db.session.get(User, new_tid), counts=counts,
            scope=scope, venue=venue, new_name=new_name,
            slots_json=json.dumps([[wd, st.strftime("%H:%M"), en.strftime("%H:%M")]
                                   for wd, st, en in slots]),
            **_lists())

    # ── safe to apply ───────────────────────────────────────────────────
    removed = g.sessions.filter(ClassSchedule.date >= from_d).delete(
        synchronize_session=False)
    for sl in list(g.slots):
        db.session.delete(sl)
    db.session.flush()
    for wd, st, en in slots:
        db.session.add(ClassSlot(group_id=g.id, weekday=wd,
                                 start_time=st, end_time=en))
    g.teacher_id = new_tid
    g.venue = venue
    if new_name and new_name != g.name:
        g.name = new_name[:160]
    g.generated_to = from_d - timedelta(days=1)
    db.session.flush()
    # the slot collection is stale after the swap; reload it so the rebuilt
    # sessions point at the new slots rather than the deleted ones
    db.session.expire(g, ["slots"])
    res = generate_group(g)
    if new_name:
        # the label is copied onto each dated class when it is built, so a
        # rename has to reach the sessions as well as the class itself
        for x in g.sessions.filter(ClassSchedule.date >= from_d).all():
            x.task = g.name
        db.session.commit()

    clear_orphan_slot_links()
    log_action("class-amend",
               f"Class {g.id} '{g.name}': teacher={new_tid}, "
               f"{len(slots)} slot(s), {removed} cleared, {res['made']} rebuilt")

    msg = (f"Timetable updated. {removed} old session(s) cleared, "
           f"{res['made']} rebuilt on the new pattern")
    if res["clash"] or res["off"]:
        msg += f", {res['clash'] + res['off']} date(s) could not be used"
    flash(msg + ".", "success" if res["made"] else "warning")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/amend-confirm", methods=["POST"])
@login_required
@admin_only
def class_amend_confirm(gid):
    """Second pass on an amendment, once the administrator has chosen."""
    from datetime import time as dtime
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    try:
        proposed = json.loads(request.form.get("slots_json", "[]"))
    except ValueError:
        flash("Something went wrong. Please set the times again.", "danger")
        return redirect(url_for("admin.class_detail", gid=gid))

    base_tid = request.form.get("teacher_id", type=int) or g.teacher_id
    scope = request.form.get("scope", "future")
    venue = request.form.get("venue", g.venue)
    new_name = request.form.get("name", "").strip()

    keep = []
    for i, (wd, a, b) in enumerate(proposed):
        choice = request.form.get(f"fix_{i}", "keep")
        if choice == "skip":
            continue
        if choice.startswith("time:"):
            span = choice[5:]
            if "-" not in span:
                continue
            na, nb = span.split("-", 1)
            keep.append((int(wd), na.strip(), nb.strip(), base_tid))
        elif choice.startswith("teacher:"):
            keep.append((int(wd), a, b, int(choice.split(":")[1])))
        else:
            keep.append((int(wd), a, b, base_tid))

    if not keep:
        flash("Every day was left out, so the timetable was not changed.",
              "warning")
        return redirect(url_for("admin.class_detail", gid=gid))

    # A class holds one teacher, so a split across teachers is refused here
    # rather than silently creating a second class behind the scenes.
    teachers = {t for _, _, _, t in keep}
    if len(teachers) > 1:
        flash("A single class can only have one teacher. Give the other days "
              "to a separate class instead.", "danger")
        return redirect(url_for("admin.class_detail", gid=gid))
    new_tid = teachers.pop()

    from_d = date.today() if scope == "future" else g.start_date
    removed = g.sessions.filter(ClassSchedule.date >= from_d).delete(
        synchronize_session=False)
    for sl in list(g.slots):
        db.session.delete(sl)
    db.session.flush()
    for wd, a, b, _ in keep:
        db.session.add(ClassSlot(
            group_id=g.id, weekday=wd,
            start_time=dtime(*[int(x) for x in a.split(":")]),
            end_time=dtime(*[int(x) for x in b.split(":")])))
    g.teacher_id = new_tid
    g.venue = venue
    if new_name and new_name != g.name:
        g.name = new_name[:160]
    g.generated_to = from_d - timedelta(days=1)
    db.session.flush()
    db.session.expire(g, ["slots"])
    res = generate_group(g)
    if new_name:
        # the label is copied onto each dated class when it is built, so a
        # rename has to reach the sessions as well as the class itself
        for x in g.sessions.filter(ClassSchedule.date >= from_d).all():
            x.task = g.name
        db.session.commit()

    clear_orphan_slot_links()
    log_action("class-amend",
               f"Class {g.id} '{g.name}' amended after resolution: "
               f"{len(keep)} slot(s), {res['made']} rebuilt")
    skipped = len(proposed) - len(keep)
    msg = f"{res['made']} class(es) rebuilt"
    if skipped:
        msg += f", {skipped} day(s) left out as you chose"
    flash(msg + ".", "success" if res["made"] else "warning")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/students", methods=["POST"])
@login_required
@admin_only
def class_students(gid):
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    action = request.form.get("action", "add")
    if action == "remove":
        sid = request.form.get("student_id", type=int)
        m = GroupStudent.query.filter_by(group_id=gid, student_id=sid).first()
        if m:
            db.session.delete(m)
            db.session.commit()
            flash("Student removed from this class.", "success")
        return redirect(url_for("admin.class_detail", gid=gid))

    added = 0
    for sid in [int(x) for x in request.form.getlist("student_ids")]:
        if GroupStudent.query.filter_by(group_id=gid, student_id=sid).first():
            continue
        db.session.add(GroupStudent(group_id=gid, student_id=sid))
        added += 1
        if g.course_id and not ClassAssignment.query.filter_by(
                course_id=g.course_id, student_id=sid).first():
            db.session.add(ClassAssignment(course_id=g.course_id,
                                           teacher_id=g.teacher_id,
                                           student_id=sid))
    db.session.commit()
    flash(f"{added} student(s) added.", "success")
    log_action("class-roll", f"Class {g.id} '{g.name}' roll changed")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/pause", methods=["POST"])
@login_required
@admin_only
def class_pause(gid):
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    frm = parse_date(request.form.get("pause_from")) or date.today()
    to  = parse_date(request.form.get("pause_to"))
    n = pause_group(g, frm, to, request.form.get("note", "").strip())
    span = (f"{frm.strftime('%d %b')} to {to.strftime('%d %b %Y')}"
            if to else f"from {frm.strftime('%d %b %Y')}")
    flash(f"'{g.name}' paused {span}. {n} class(es) cancelled.", "success")
    log_action("class-pause", f"Class {g.id} '{g.name}' paused")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/resume", methods=["POST"])
@login_required
@admin_only
def class_resume(gid):
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    back, made = resume_group(g)
    flash(f"'{g.name}' running again. {back} class(es) reinstated, "
          f"{made} new one(s) built.", "success")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/stop", methods=["POST"])
@login_required
@admin_only
def class_stop(gid):
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    frm = parse_date(request.form.get("from_date")) or date.today()
    n = stop_group(g, frm, request.form.get("note", "").strip())
    flash(f"'{g.name}' stopped. {n} future class(es) cancelled. "
          f"Everything already taught is kept.", "success")
    log_action("class-stop", f"Class {g.id} '{g.name}' stopped")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/extend", methods=["POST"])
@login_required
@admin_only
def class_extend(gid):
    """Extend by a date, by a number of classes, or remove the end date."""
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    mode = request.form.get("mode", "date")

    if mode == "forever":
        g.end_date = None
    elif mode == "count":
        want = request.form.get("add_classes", type=int)
        if not want or want < 1:
            flash("How many more classes? Give a number of 1 or more.", "danger")
            return redirect(url_for("admin.class_detail", gid=gid))
        from_d = max(date.today(), (g.end_date or date.today()) + timedelta(days=1))
        days = {s.weekday for s in g.slots}
        if not days:
            flash("This class has no days set, so there is nothing to extend.",
                  "danger")
            return redirect(url_for("admin.class_detail", gid=gid))
        before = g.sessions.filter(ClassSchedule.status == "Scheduled").count()
        g.end_date = date_for_count(days, from_d, want * 3, g.teacher_id)
        if g.status == "Stopped":
            g.status = "Active"
        db.session.commit()
        generate_group(g)
        # trim back to exactly the number asked for
        added = (g.sessions.filter(ClassSchedule.status == "Scheduled",
                                   ClassSchedule.date >= from_d)
                 .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
        for x in added[want:]:
            db.session.delete(x)
        kept = g.sessions.filter(ClassSchedule.status == "Scheduled").all()
        if kept:
            g.end_date = max(x.date for x in kept)
            g.generated_to = g.end_date
        db.session.commit()
        log_action("class-extend", f"Class {g.id} '{g.name}': +{want} class(es)")
        now = len(kept)
        flash(f"{now - before} class(es) added, running to "
              f"{g.end_date.strftime('%d %b %Y')}.", "success")
        return redirect(url_for("admin.class_detail", gid=gid))
    else:
        nd = parse_date(request.form.get("new_end"))
        if not nd:
            flash("Give a new finish date.", "danger")
            return redirect(url_for("admin.class_detail", gid=gid))
        g.end_date = nd

    if g.status == "Stopped":
        g.status = "Active"
    db.session.commit()
    res = generate_group(g)
    log_action("class-extend", f"Class {g.id} '{g.name}': mode={mode}")
    flash(f"'{g.name}' extended. {res['made']} class(es) added, "
          f"running to {res['upto'].strftime('%d %b %Y')}.", "success")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/delete-range", methods=["POST"])
@login_required
@admin_only
def class_delete_range(gid):
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    frm = parse_date(request.form.get("del_from")) or date.today()
    to  = parse_date(request.form.get("del_to"))
    n = delete_group_range(g, frm, to)
    flash(f"{n} class(es) deleted.", "success")
    return redirect(url_for("admin.class_detail", gid=gid))


@bp.route("/admin/classes/<int:gid>/delete", methods=["POST"])
@login_required
@admin_only
def class_delete(gid):
    g = db.session.get(ClassGroup, gid)
    if not g:
        abort(404)
    nm, n_sess = g.name, g.sessions.count()
    if request.form.get("confirm") != "DELETE":
        flash("Type DELETE to confirm.", "danger")
        return redirect(url_for("admin.class_detail", gid=gid))
    name = g.name
    db.session.delete(g)
    db.session.commit()
    flash(f"'{name}' and all its classes deleted.", "success")
    log_action("class-delete", f"Class {gid} '{nm}' DELETED with {n_sess} session(s)")
    return redirect(url_for("admin.classes"))


@bp.route("/admin/classes/top-up", methods=["POST"])
@login_required
@admin_only
def classes_top_up():
    months = request.form.get("months", type=int, default=6)
    upto = date.today() + timedelta(days=months * 30)
    n = top_up_groups(upto)
    flash(f"{n} class(es) built, out to {upto.strftime('%d %b %Y')}.", "success")
    return redirect(url_for("admin.classes"))


# ── live slot check, used by the create form ──────────────────────────────

@bp.route("/admin/api/check-slot")
@login_required
@admin_only
def api_check_slot():
    """
    Judge a proposed weekly slot across the dates it would actually run on,
    and — when it will not fit — say plainly what would.
    """
    from datetime import time as dtime
    tid   = request.args.get("teacher_id", type=int)
    wd    = request.args.get("weekday", type=int)
    a     = request.args.get("from", "")
    b     = request.args.get("to", "")
    sids  = [int(x) for x in request.args.getlist("student_ids") if x]
    start = parse_date(request.args.get("start")) or date.today()
    end   = parse_date(request.args.get("end"))

    if not tid or wd is None or not a or not b:
        return jsonify({"status": "unknown", "message": "", "options": []})
    try:
        st = dtime(*[int(x) for x in a.split(":")[:2]])
        en = dtime(*[int(x) for x in b.split(":")[:2]])
    except (ValueError, TypeError):
        return jsonify({"status": "unknown", "message": "", "options": []})
    if en <= st:
        return jsonify({"status": "clash", "options": [],
                        "message": "The finish time must be after the start."})

    res = analyse_slot(tid, wd, st, en, sids, start, end, occurrences=8)
    if res["total"] == 0:
        return jsonify({"status": "unknown", "options": [],
                        "message": "No dates fall on that day in the range you picked."})

    day = ["Monday", "Tuesday", "Wednesday", "Thursday",
           "Friday", "Saturday", "Sunday"][wd]

    if res["clean"]:
        return jsonify({"status": "ok", "options": [],
                        "message": f"Free on all {res['total']} of the next {day}s."})

    opts = slot_options(tid, res["sample"], st, en, sids)
    out = {
        "status": res["status"],
        "message": res["message"],
        "summary": (f"Works on {res['ok']} of the next {res['total']} {day}s."
                    if res["ok"] else
                    f"Blocked on all {res['total']} of the next {day}s."),
        "bad_dates": [d.strftime("%d %b") for d in res["bad_dates"][:5]],
        "options": [],
    }
    # Other teachers, same time — the student loses nothing
    for o in opts["teachers"]:
        out["options"].append({
            "kind": "teacher", "teacher_id": o["teacher"].id,
            "from": st.strftime("%H:%M"), "to": en.strftime("%H:%M"),
            "label": f"Keep {fmt(st)} with {o['teacher'].full_name}",
            "note": "same time, different teacher" + (f" ({o['note']})" if o["note"] else ""),
        })
    # Same teacher, nearest working time
    for o in opts["times"]:
        out["options"].append({
            "kind": "time",
            "from": o["start"].strftime("%H:%M"), "to": o["end"].strftime("%H:%M"),
            "label": f"Move to {fmt(o['start'])} - {fmt(o['end'])}",
            "note": o["label"],
        })
    return jsonify(out)


# ═══════════════════════════════════════════════════ DAILY ROOMS ══════════

@bp.route("/admin/daily", methods=["GET"])
@login_required
@admin_only
def daily():
    """Pick a date, see that day's classes, type the rooms, save, print."""
    on = parse_date(request.args.get("date")) or date.today()
    tid = request.args.get("teacher_id", type=int)
    rows = get_daily_schedule(on, teacher_id=tid)
    live = [r for r in rows if r.status != "Cancelled"]
    stats = {
        "classes": len(live),
        "with_room": sum(1 for r in live if r.room),
        "online": sum(1 for r in live
                      if (r.venue or "").lower() in ("online", "zoom")),
        "students": sum(r.head_count or 0 for r in live),
    }
    return render_template("admin/daily.html", on=on, rows=rows, stats=stats,
                           prev_d=on - timedelta(days=1),
                           next_d=on + timedelta(days=1),
                           filter_tid=tid, today=date.today(), **_lists())


@bp.route("/admin/daily/rooms", methods=["POST"])
@login_required
@admin_only
def daily_rooms():
    """Save every room typed on the day. Nothing else is touched."""
    on = parse_date(request.form.get("date")) or date.today()
    mapping = {}
    for k, v in request.form.items():
        if k.startswith("room_"):
            mapping[k[5:]] = v
    n = update_schedule_rooms(mapping)
    flash(f"{n} room(s) saved for {on.strftime('%A %d %B %Y')}."
          if n else "No room changes to save.", "success" if n else "info")
    log_action("rooms", f"{n} room(s) set for {on.isoformat()}")
    return redirect(url_for("admin.daily", date=on.isoformat(),
                            teacher_id=request.form.get("teacher_id") or None))


@bp.route("/admin/daily/pdf")
@login_required
@admin_only
def daily_pdf():
    try:
        from pdf_export import daily_routine_pdf
    except Exception:
        return _no_pdf()
    on = parse_date(request.args.get("date")) or date.today()
    tid = request.args.get("teacher_id", type=int)
    rows = [r for r in get_daily_schedule(on, teacher_id=tid)
            if r.status != "Cancelled"]
    try:
        data = daily_routine_pdf(rows, on)
    except RuntimeError:
        return _no_pdf()
    return _pdf(data, f"daily_routine_{on.isoformat()}.pdf")


@bp.route("/admin/activity")
@login_required
@admin_only
def activity():
    """Who changed what, most recent first."""
    who    = request.args.get("actor", type=int)
    action = request.args.get("action", "")
    q = AuditLog.query
    if who:
        q = q.filter_by(actor_id=who)
    if action:
        q = q.filter_by(action=action)
    rows = q.order_by(AuditLog.created_at.desc()).limit(300).all()
    actions = sorted({a.action for a in AuditLog.query
                      .with_entities(AuditLog.action).distinct()})
    staff = (User.query.filter(User.role.in_(["ADMIN", "TEACHER"]))
             .order_by(User.full_name).all())
    return render_template("admin/activity.html", rows=rows, actions=actions,
                           staff=staff, f_actor=who, f_action=action,
                           total=AuditLog.query.count(), **_lists())


@bp.route("/admin/backup")
@login_required
@admin_only
def backup():
    """
    Download a copy of the whole database.

    Everything the centre has is in this one file, so keeping a dated copy
    somewhere other than the server is the only real protection against a
    mistake or a lost account.
    """
    from flask import after_this_request
    try:
        path, name = backup_database()
    except RuntimeError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.overview"))

    @after_this_request
    def cleanup(resp):
        try:
            os.remove(path)
        except OSError:
            pass
        return resp

    log_action("backup", f"Database downloaded as {name}")
    return send_file(path, as_attachment=True, download_name=name,
                     mimetype="application/x-sqlite3")


@bp.route("/admin/classes/extend-many", methods=["POST"])
@login_required
@admin_only
def classes_extend_many():
    """Extend several classes at once, by a count or by removing the end date."""
    ids = [int(x) for x in request.form.getlist("group_ids") if x.isdigit()]
    mode = request.form.get("mode", "count")
    want = request.form.get("add_classes", type=int)
    if not ids:
        flash("Tick the classes you want to extend.", "danger")
        return redirect(url_for("admin.classes"))
    if mode == "count" and (not want or want < 1):
        flash("How many classes? Give a number of 1 or more.", "danger")
        return redirect(url_for("admin.classes"))

    done = added = skipped = 0
    for gid in ids:
        g = db.session.get(ClassGroup, gid)
        if not g:
            continue
        if mode == "forever":
            g.end_date = None
            if g.status == "Stopped":
                g.status = "Active"
            db.session.commit()
            r = generate_group(g)
            added += r["made"]
            done += 1
            continue

        days = {sl.weekday for sl in g.slots}
        if not days:
            skipped += 1
            continue
        from_d = max(date.today(),
                     (g.end_date or date.today()) + timedelta(days=1))
        before = g.sessions.filter(ClassSchedule.status == "Scheduled").count()
        g.end_date = date_for_count(days, from_d, want * 3, g.teacher_id)
        if g.status == "Stopped":
            g.status = "Active"
        db.session.commit()
        generate_group(g)
        fresh = (g.sessions.filter(ClassSchedule.status == "Scheduled",
                                   ClassSchedule.date >= from_d)
                 .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
        for x in fresh[want:]:
            db.session.delete(x)
        kept = g.sessions.filter(ClassSchedule.status == "Scheduled").all()
        if kept:
            g.end_date = max(x.date for x in kept)
            g.generated_to = g.end_date
        db.session.commit()
        added += len(kept) - before
        done += 1

    log_action("class-extend-many",
               f"{done} class(es) extended, mode={mode}, {added} session(s) added")
    msg = (f"{done} class(es) extended — {added} class(es) added."
           if mode == "count" else
           f"{done} class(es) now run until you stop them — "
           f"{added} class(es) added.")
    if skipped:
        msg += f" {skipped} skipped for having no days set."
    flash(msg, "success" if done else "warning")
    return redirect(url_for("admin.classes"))


@bp.route("/admin/data-check")
@login_required
@admin_only
def data_check():
    """
    Occurrences attached to neither a class nor a student. They cannot show on
    anyone's routine, so they are listed here to be repaired rather than
    quietly swept into a course-wide query.
    """
    rows = unlinked_schedules()
    stranded = stranded_students()
    return render_template("admin/data_check.html", rows=rows,
                           stranded=stranded, **_lists())


@bp.route("/admin/data-check/attach", methods=["POST"])
@login_required
@admin_only
def data_check_attach():
    """Put stranded students into the single obvious class for their subject."""
    only = request.form.getlist("student_ids")
    targets = stranded_students()
    if only:
        keep = {int(x) for x in only}
        targets = [t for t in targets if t["student"].id in keep]
    added = 0
    touched = 0
    for t in targets:
        if not t["certain"]:
            continue
        for g in t["suggest"]:
            if GroupStudent.query.filter_by(group_id=g.id,
                                            student_id=t["student"].id).first():
                continue
            db.session.add(GroupStudent(group_id=g.id,
                                        student_id=t["student"].id))
            added += 1
        touched += 1
    db.session.commit()
    flash(f"{touched} student(s) attached to {added} class(es). "
          f"Their routines will now print." if added else
          "Nothing could be attached automatically — those subjects have "
          "more than one class, so choose by hand.",
          "success" if added else "warning")
    return redirect(url_for("admin.data_check"))


# ═══════════════════════════════════════════════════ TEACHER BLOCKS ═══════

@bp.route("/admin/teachers/<int:tid>/blocks", methods=["POST"])
@login_required
@admin_only
def teacher_block_add(tid):
    from datetime import time as dtime
    t = db.session.get(User, tid)
    if not t:
        abort(404)
    try:
        st = dtime(*[int(x) for x in request.form.get("start_time", "").split(":")[:2]])
        en = dtime(*[int(x) for x in request.form.get("end_time", "").split(":")[:2]])
    except (ValueError, TypeError):
        flash("Give a valid start and finish time.", "danger")
        return redirect(url_for("admin.edit_teacher", tid=tid))
    wd_raw = request.form.get("weekday", "")
    db.session.add(TeacherBlock(
        teacher_id=tid,
        label=request.form.get("label", "").strip() or "Break",
        weekday=int(wd_raw) if wd_raw not in ("", "any") else None,
        start_time=st, end_time=en,
        on_date=parse_date(request.form.get("on_date"))))
    db.session.commit()
    flash("Protected time added. Nothing can be booked over it.", "success")
    return redirect(url_for("admin.edit_teacher", tid=tid))


@bp.route("/admin/blocks/<int:bid>/delete", methods=["POST"])
@login_required
@admin_only
def teacher_block_delete(bid):
    b = db.session.get(TeacherBlock, bid)
    if not b:
        abort(404)
    tid = b.teacher_id
    db.session.delete(b)
    db.session.commit()
    flash("Protected time removed.", "success")
    return redirect(url_for("admin.edit_teacher", tid=tid))


# ═══════════════════════════════════════════════════ REPORTS ════════════

@bp.route("/admin/reports")
@login_required
@admin_only
def reports():
    start, end, label = window_from_request()
    at_risk = students_at_risk(start, end)

    # Teacher workload
    workload = []
    for t in User.query.filter_by(role="TEACHER", status="ACTIVE").all():
        q = ClassSchedule.query.filter(
            ClassSchedule.teacher_id == t.id,
            ClassSchedule.date >= start,
            ClassSchedule.date <= end,
            ClassSchedule.class_type.notin_(["Break","Other"]),
        )
        total    = q.count()
        done     = q.filter_by(status="Completed").count()
        cancelled= q.filter_by(status="Cancelled").count()
        absent_s = q.filter_by(status="Student Absent").count()
        hours    = sum((c.duration_mins or 60) for c in q.all()) / 60
        workload.append({"teacher": t, "total": total, "done": done,
                         "cancelled": cancelled, "student_absent": absent_s,
                         "hours": round(hours, 1)})

    return render_template("admin/reports.html",
                           at_risk=at_risk, workload=workload,
                           window_label=label, **_lists())


# ═══════════════════════════════════════════════════ NOTICES ════════════

@bp.route("/admin/notices")
@login_required
@admin_only
def notices():
    all_notices = (Announcement.query
                   .order_by(Announcement.is_urgent.desc(),
                              Announcement.created_at.desc()).all())
    lists = _lists()
    lists.pop("notices", None)
    return render_template("admin/notices.html", notices=all_notices, **lists)


@bp.route("/admin/notices/new", methods=["POST"])
@login_required
@admin_only
def create_notice():
    title = request.form.get("title","").strip()
    if not title:
        flash("Title required.", "danger")
        return redirect(url_for("admin.notices"))
    n = Announcement(
        author_id=current_user.id,
        title=title,
        body=request.form.get("body","").strip() or None,
        audience=request.form.get("audience","STUDENTS"),
        branch=request.form.get("branch") or None,

        is_urgent=request.form.get("is_urgent") == "1",
        expires_on=parse_date(request.form.get("expires_on")),
    )
    db.session.add(n)
    db.session.commit()
    flash("Notice posted.", "success")
    return redirect(url_for("admin.notices"))


@bp.route("/admin/notices/<int:nid>/delete", methods=["POST"])
@login_required
@admin_only
def delete_notice(nid):
    n = db.session.get(Announcement, nid)
    if n:
        db.session.delete(n)
        db.session.commit()
    flash("Notice deleted.", "success")
    return redirect(url_for("admin.notices"))
