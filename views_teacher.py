"""Teacher views — course-first tabbed interface."""
import os
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_file, url_for)
from flask_login import current_user, login_required

from helpers import (attendance_grid_csv, check_slot, course_students,
                     day_timeline, fmt, sync_assessment_rows,
                     log_action, marksheet_csv, notices_for, outstanding_for,
                     parse_date, role_required, save_upload, upload_path,
                     window_from_request)
from models import (ASSESSMENT_KINDS, Announcement, Assessment, Attendance,
                    ClassAssignment, ClassGroup, ClassSchedule, CourseMaterial,
                    Course, GroupStudent, LessonLog, Result,
                    ScheduleAttendance, User, db)

bp = Blueprint("teacher", __name__)
teacher_only = role_required("ADMIN", "TEACHER")


def _my_courses():
    """Courses reached either through enrolment or through a class this teacher runs."""
    if current_user.is_admin:
        return Course.query.filter_by(is_archived=False).order_by(Course.course_code).all()
    found = {a.course for a in current_user.teaching_assignments
             if a.course and not a.course.is_archived}
    for g in ClassGroup.query.filter_by(teacher_id=current_user.id).all():
        if g.course and not g.course.is_archived:
            found.add(g.course)
    return sorted(found, key=lambda c: c.course_code)


def _my_students(course_id):
    """
    Everyone on this subject. Narrowed to the teacher's own classes where they
    run one, but a teacher who runs none still sees the whole subject — they
    may have been asked to set or mark the work anyway, and returning nobody
    silently produced assignments that reached no student.
    """
    return course_students(course_id,
                           None if current_user.is_admin else current_user.id)


# ─────────────────────────────────────────── my courses list ───────────────

@bp.route("/teacher")
@login_required
@teacher_only
def my_courses():
    courses = _my_courses()
    return render_template("teacher/courses.html", courses=courses,
                           notices=notices_for(current_user))


# ─────────────────────────────────────────── single course (tabbed) ────────

@bp.route("/teacher/course/<int:cid>")
@login_required
@teacher_only
def course(cid):
    c = db.session.get(Course, cid)
    if not c:
        abort(404)
    students  = _my_students(cid)
    tab       = request.args.get("tab", "register")
    start, end, label = window_from_request()

    # per-tab data
    extra = {}
    if tab == "register":
        class_date = parse_date(request.args.get("class_date")) or date.today()

        # A register belongs to ONE class, not to a whole subject. Two
        # one-to-one students in the same subject sit at different times and
        # must never share a list.
        q = (ClassSchedule.query
             .filter(ClassSchedule.date == class_date,
                     ClassSchedule.course_id == cid,
                     ClassSchedule.status != "Cancelled",
                     ClassSchedule.class_type != "Break"))
        if not current_user.is_admin:
            q = q.filter(ClassSchedule.teacher_id == current_user.id)
        sessions = q.order_by(ClassSchedule.start_time).all()

        chosen_id = request.args.get("session_id", type=int)
        session = None
        if sessions:
            session = next((x for x in sessions if x.id == chosen_id), sessions[0])

        roll = []
        if session:
            if session.group:
                roll = sorted((m.student for m in session.group.members if m.student),
                              key=lambda u: u.full_name)
            elif session.student:
                roll = [session.student]

        existing = {}
        if session:
            existing = {a.student_id: a.status for a in
                        ScheduleAttendance.query.filter_by(
                            schedule_id=session.id).all()}
            if not existing:
                existing = {a.student_id: a.status for a in
                            Attendance.query.filter_by(
                                course_id=cid, date=class_date).all()
                            if a.student_id in {s.id for s in roll}}

        marked = (ScheduleAttendance.query
                  .join(ClassSchedule,
                        ScheduleAttendance.schedule_id == ClassSchedule.id)
                  .filter(ClassSchedule.course_id == cid).all())
        marked_dates = sorted({a.schedule.date for a in marked if a.schedule},
                              reverse=True)

        extra = {"class_date": class_date, "existing": existing,
                 "marked_dates": marked_dates, "sessions": sessions,
                 "session": session, "roll": roll}

    elif tab == "lessons":
        extra["logs"] = (LessonLog.query.filter_by(course_id=cid)
                         .order_by(LessonLog.class_date.desc()).all())

    elif tab == "work":
        extra["assessments"] = (Assessment.query.filter_by(course_id=cid)
                                 .order_by(Assessment.assigned_date.desc()).all())
        extra["kinds"] = ASSESSMENT_KINDS

    elif tab == "marks":
        assessments = (Assessment.query.filter_by(course_id=cid)
                       .order_by(Assessment.assigned_date.desc()).all())
        results = {}
        for a in assessments:
            results[a.id] = {r.student_id: r for r in
                              Result.query.filter_by(assessment_id=a.id).all()}
        extra = {"assessments": assessments, "results": results}

    elif tab == "schedule":
        q = ClassSchedule.query.filter_by(course_id=cid)
        if not current_user.is_admin:
            q = q.filter(ClassSchedule.teacher_id == current_user.id)
        extra["schedules"] = q.order_by(ClassSchedule.date.desc()).all()

    elif tab == "materials":
        extra["materials"] = (CourseMaterial.query.filter_by(course_id=cid)
                              .order_by(CourseMaterial.uploaded_at.desc()).all())

    elif tab == "notices":
        extra["notices"] = (Announcement.query.filter_by(course_id=cid)
                            .order_by(Announcement.created_at.desc()).all())

    return render_template("teacher/course.html",
                           course=c, students=students, tab=tab,
                           window_label=label, start=start, end=end,
                           today_str=date.today().isoformat(),
                           **extra)


# ─────────────────────────────────────────── register ──────────────────────

@bp.route("/teacher/course/<int:cid>/register", methods=["POST"])
@login_required
@teacher_only
def save_register(cid):
    """
    Save the register for ONE class on one date.

    Attendance is written against the dated session, so two one-to-one
    students in the same subject keep separate records even when their
    classes fall on the same day.
    """
    c = db.session.get(Course, cid)
    if not c:
        abort(404)
    class_date = parse_date(request.form.get("class_date")) or date.today()
    sid = request.form.get("session_id", type=int)
    session = db.session.get(ClassSchedule, sid) if sid else None
    if not session or session.course_id != cid:
        flash("That class could not be found. Pick the date again.", "danger")
        return redirect(url_for("teacher.course", cid=cid, tab="register",
                                class_date=class_date.isoformat()))
    if (not current_user.is_admin
            and session.teacher_id != current_user.id):
        abort(403)

    if session.group:
        roll = [m.student for m in session.group.members if m.student]
    elif session.student:
        roll = [session.student]
    else:
        roll = []

    saved = 0
    for s in roll:
        status = request.form.get(f"status_{s.id}")
        if not status:
            continue
        # against the session, so each class keeps its own record
        row = ScheduleAttendance.query.filter_by(
            schedule_id=session.id, student_id=s.id).first()
        if row:
            row.status = status
        else:
            db.session.add(ScheduleAttendance(
                schedule_id=session.id, student_id=s.id, status=status))
        # and against the course, which is what the percentages read
        old = Attendance.query.filter_by(
            student_id=s.id, course_id=cid, date=class_date).first()
        if old:
            old.status = status
        else:
            db.session.add(Attendance(student_id=s.id, course_id=cid,
                                      date=class_date, status=status))
        saved += 1
    db.session.commit()
    log_action("register",
               f"{session.task} on {class_date.isoformat()}: {saved} student(s)")
    flash(f"Register saved for {session.task} — "
          f"{class_date.strftime('%d %b %Y')} ({saved} student(s)).", "success")
    return redirect(url_for("teacher.course", cid=cid, tab="register",
                            class_date=class_date.isoformat(),
                            session_id=session.id))


# ─────────────────────────────────────────── lesson log ────────────────────

@bp.route("/teacher/course/<int:cid>/log", methods=["POST"])
@login_required
@teacher_only
def log_lesson(cid):
    topic = request.form.get("topic_taught","").strip()
    if not topic:
        flash("Topic is required.", "danger")
        return redirect(url_for("teacher.course", cid=cid, tab="lessons"))
    ll = LessonLog(
        course_id=cid,
        teacher_id=current_user.id,
        class_date=parse_date(request.form.get("class_date")) or date.today(),
        topic_taught=topic,
        summary_notes=request.form.get("summary_notes","").strip() or None,
        homework=request.form.get("homework","").strip() or None,
    )
    db.session.add(ll)
    db.session.commit()
    flash("Lesson logged.", "success")
    return redirect(url_for("teacher.course", cid=cid, tab="lessons"))


@bp.route("/teacher/lesson/<int:lid>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_lesson(lid):
    ll = db.session.get(LessonLog, lid)
    if not ll:
        abort(404)
    if not (current_user.is_admin or ll.teacher_id == current_user.id
            or _may_manage_course(ll.course_id)):
        abort(403)
    cid = ll.course_id
    db.session.delete(ll)
    db.session.commit()
    flash("Log entry deleted.", "success")
    return redirect(url_for("teacher.course", cid=cid, tab="lessons"))


# ─────────────────────────────────────────── work set ──────────────────────

@bp.route("/teacher/course/<int:cid>/work/new", methods=["POST"])
@login_required
@teacher_only
def create_work(cid):
    title = request.form.get("title","").strip()
    if not title:
        flash("Title required.", "danger")
        return redirect(url_for("teacher.course", cid=cid, tab="work"))
    a = Assessment(
        course_id=cid,
        teacher_id=current_user.id,
        title=title,
        kind=request.form.get("kind","Assignment"),
        instructions=request.form.get("instructions","").strip() or None,
        attachment_link=request.form.get("attachment_link","").strip() or None,
        assigned_date=parse_date(request.form.get("assigned_date")) or date.today(),
        due_date=parse_date(request.form.get("due_date")),
        max_score=float(request.form.get("max_score",100) or 100),
        # a checkbox sends nothing when unticked, so defaulting to "1" made
        # every piece of work require a hand-in and the box did nothing
        needs_submission=request.form.get("needs_submission") in
                         ("1", "on", "true", "yes"),
        is_published=request.form.get("is_published","1") == "1",
    )
    db.session.add(a)
    db.session.flush()

    up = request.files.get("attachment")
    if up and up.filename:
        try:
            nm, key, mime, size = save_upload(up, "assignments")
            a.attachment_name, a.attachment_key = nm, key
            a.attachment_mime, a.attachment_size = mime, size
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("teacher.course", cid=cid, tab="work"))

    db.session.commit()
    n = sync_assessment_rows(a)
    if n == 0:
        # true for a mock as much as for an assignment: with nobody on the
        # subject there is nobody to hand it to, or to mark
        what = "hand it in" if a.needs_submission else "be marked for it"
        flash(f"'{title}' was created, but no student is attached to "
              f"{a.course.course_code if a.course else 'this subject'} yet, so "
              f"nobody can {what}. Add students to a class first.", "warning")
        return redirect(url_for("teacher.course", cid=cid, tab="work"))
    flash(f"'{title}' assigned to {n} student(s)"
          + (f" with {a.attachment_name}." if a.attachment_key else "."),
          "success")
    return redirect(url_for("teacher.course", cid=cid, tab="work"))


@bp.route("/teacher/work/<int:aid>/toggle", methods=["POST"])
@login_required
@teacher_only
def toggle_publish(aid):
    a = db.session.get(Assessment, aid)
    if not a:
        abort(404)
    if not _may_manage(a):
        abort(403)
    a.is_published = not a.is_published
    db.session.commit()
    return redirect(url_for("teacher.course", cid=a.course_id, tab="work"))


@bp.route("/teacher/work/<int:aid>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_work(aid):
    a = db.session.get(Assessment, aid)
    if not a:
        abort(404)
    if not _may_manage(a):
        abort(403)
    cid = a.course_id
    db.session.delete(a)
    db.session.commit()
    flash("Work item deleted.", "success")
    return redirect(url_for("teacher.course", cid=cid, tab="work"))


# ─────────────────────────────────────────── marks ─────────────────────────

@bp.route("/teacher/assessment/<int:aid>/marks", methods=["POST"])
@login_required
@teacher_only
def save_marks(aid):
    a = db.session.get(Assessment, aid)
    if not a:
        abort(404)
    if not _may_manage(a):
        abort(403)
    students = _my_students(a.course_id)
    saved = 0
    blocked = []
    for s in students:
        score_raw    = request.form.get(f"score_{s.id}","").strip()
        feedback_raw = request.form.get(f"feedback_{s.id}","").strip()
        if not score_raw and not feedback_raw:
            continue
        r = Result.query.filter_by(assessment_id=aid, student_id=s.id).first()
        if not r:
            r = Result(assessment_id=aid, student_id=s.id)
            db.session.add(r)
        if score_raw:
            if not r.can_mark:
                blocked.append(s.full_name)
                continue
            try:
                r.score    = float(score_raw)
                r.marked_at = datetime.utcnow()
                log_action("mark", f"Assessment {aid} student {s.id} score {r.score}")
            except ValueError:
                pass
        if feedback_raw:
            r.feedback = feedback_raw
        saved += 1
    db.session.commit()
    msg = f"Marks saved for {saved} student(s)."
    if blocked:
        msg += (f" Not marked until receipt is confirmed: "
                f"{', '.join(blocked[:5])}"
                + (f" and {len(blocked)-5} more" if len(blocked) > 5 else "") + ".")
    flash(msg, "warning" if blocked else "success")
    return redirect(url_for("teacher.course", cid=a.course_id, tab="marks"))


# ─────────────────────────────────────────── schedule attendance ────────────

@bp.route("/teacher/schedule/<int:sid>/attendance", methods=["GET","POST"])
@login_required
@teacher_only
def mark_schedule_att(sid):
    cls = db.session.get(ClassSchedule, sid)
    if not cls:
        abort(404)
    if request.method == "POST":
        if cls.class_type == "1-on-1" and cls.student_id:
            status  = request.form.get("status","Present")
            remarks = request.form.get("remarks","").strip()
            existing = ScheduleAttendance.query.filter_by(
                schedule_id=sid, student_id=cls.student_id).first()
            if existing:
                existing.status = status
                existing.remarks = remarks
                existing.marked_at = datetime.utcnow()
            else:
                db.session.add(ScheduleAttendance(
                    schedule_id=sid, student_id=cls.student_id,
                    status=status, remarks=remarks,
                    marked_by=current_user.id))
            # update schedule status
            cls.status = {
                "Present": "Completed",
                "Absent": "Student Absent",
                "Teacher Absent": "Teacher Absent",
                "Cancelled": "Cancelled",
            }.get(status, cls.status)
            db.session.commit()
            flash("Attendance marked.", "success")
        return redirect(url_for("teacher.course",
                                cid=cls.course_id or 0, tab="schedule")
                        if cls.course_id else url_for("teacher.my_courses"))
    existing = ScheduleAttendance.query.filter_by(
        schedule_id=sid, student_id=cls.student_id).first() if cls.student_id else None
    return render_template("teacher/mark_attendance.html",
                           cls=cls, existing=existing)


# ─────────────────────────────────────────── materials ─────────────────────

@bp.route("/teacher/course/<int:cid>/materials/add", methods=["POST"])
@login_required
@teacher_only
def add_material(cid):
    title   = request.form.get("title","").strip()
    link    = request.form.get("link","").strip()
    file_up = request.files.get("file_upload")
    if not title:
        flash("Title required.", "danger")
        return redirect(url_for("teacher.course", cid=cid, tab="materials"))

    used = storage_usage()
    hard = current_app.config.get("STORAGE_HARD_LIMIT", 350*1024*1024)

    if link:
        m = CourseMaterial(course_id=cid, teacher_id=current_user.id,
                           title=title, file_path_or_link=link, is_link=True)
        db.session.add(m)
        db.session.commit()
        flash("Link added.", "success")
    elif file_up and file_up.filename:
        if used >= hard:
            flash("Storage limit reached. Share as a link instead.", "danger")
            return redirect(url_for("teacher.course", cid=cid, tab="materials"))
        safe   = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file_up.filename}"
        dest   = os.path.join(current_app.config["UPLOAD_FOLDER"], safe)
        file_up.save(dest)
        size   = os.path.getsize(dest)
        m = CourseMaterial(course_id=cid, teacher_id=current_user.id,
                           title=title, file_path_or_link=safe,
                           is_link=False, file_size=size)
        db.session.add(m)
        db.session.commit()
        flash("File uploaded.", "success")
    else:
        flash("Provide a link or upload a file.", "danger")
    return redirect(url_for("teacher.course", cid=cid, tab="materials"))


@bp.route("/teacher/materials/<int:mid>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_material(mid):
    m = db.session.get(CourseMaterial, mid)
    if not m:
        abort(404)
    if not (current_user.is_admin or m.teacher_id == current_user.id
            or _may_manage_course(m.course_id)):
        abort(403)
    cid = m.course_id
    if not m.is_link:
        dest = os.path.join(current_app.config["UPLOAD_FOLDER"], m.file_path_or_link)
        if os.path.exists(dest):
            os.remove(dest)
    db.session.delete(m)
    db.session.commit()
    flash("Material deleted.", "success")
    return redirect(url_for("teacher.course", cid=cid, tab="materials"))


# ─────────────────────────────────────────── notices ───────────────────────

@bp.route("/teacher/course/<int:cid>/notices/new", methods=["POST"])
@login_required
@teacher_only
def post_notice(cid):
    title = request.form.get("title","").strip()
    if not title:
        flash("Title required.", "danger")
        return redirect(url_for("teacher.course", cid=cid, tab="notices"))
    n = Announcement(
        author_id=current_user.id,
        course_id=cid,
        audience="STUDENTS",
        title=title,
        body=request.form.get("body","").strip() or None,
        is_urgent=request.form.get("is_urgent") == "1",
        expires_on=parse_date(request.form.get("expires_on")),
    )
    db.session.add(n)
    db.session.commit()
    flash("Notice posted.", "success")
    return redirect(url_for("teacher.course", cid=cid, tab="notices"))


@bp.route("/teacher/notices/<int:nid>/delete", methods=["POST"])
@login_required
@teacher_only
def delete_notice(nid):
    n = db.session.get(Announcement, nid)
    if not n:
        abort(404)
    if not (current_user.is_admin or n.author_id == current_user.id):
        abort(403)
    cid = n.course_id
    db.session.delete(n)
    db.session.commit()
    flash("Notice deleted.", "success")
    return redirect(url_for("teacher.course", cid=cid, tab="notices"))


# ─────────────────────────────────────────── CSV exports ───────────────────

@bp.route("/teacher/course/<int:cid>/attendance.csv")
@login_required
@teacher_only
def attendance_export(cid):
    c        = db.session.get(Course, cid)
    students = _my_students(cid)
    dates    = sorted({a.date for a in Attendance.query.filter_by(course_id=cid).all()})
    return attendance_grid_csv(c, students, dates)


@bp.route("/teacher/course/<int:cid>/marks.csv")
@login_required
@teacher_only
def marksheet_export(cid):
    c           = db.session.get(Course, cid)
    students    = _my_students(cid)
    assessments = (Assessment.query.filter_by(course_id=cid)
                   .order_by(Assessment.assigned_date).all())
    return marksheet_csv(c, students, assessments)


def storage_usage():
    from helpers import storage_usage as _su
    return _su()


# ─────────────────────────────────────────── my schedule ────────────────────

@bp.route("/teacher/schedule")
@login_required
@teacher_only
def my_schedule():
    """Day, week or month — whatever the teacher needs to see."""
    view   = request.args.get("view", "week")
    anchor = parse_date(request.args.get("date")) or date.today()
    today  = date.today()
    tid    = (request.args.get("teacher_id", type=int)
              if current_user.is_admin else None) or current_user.id

    if view == "day":
        start = end = anchor
    elif view == "month":
        start = anchor.replace(day=1)
        end   = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    else:
        view  = "week"
        start = anchor - timedelta(days=anchor.weekday())
        end   = start + timedelta(days=6)

    rows = (ClassSchedule.query
            .filter(ClassSchedule.teacher_id == tid,
                    ClassSchedule.date >= start, ClassSchedule.date <= end)
            .order_by(ClassSchedule.date, ClassSchedule.start_time).all())

    days = {}
    d = start
    while d <= end:
        days[d] = []
        d += timedelta(days=1)
    for r in rows:
        if r.date in days:
            days[r.date].append(r)

    live = [r for r in rows
            if r.class_type != "Break" and r.status != "Cancelled"]
    stats = {
        "classes": len(live),
        "hours": round(sum(r.duration_mins or 0 for r in live) / 60, 1),
        "batch": sum(1 for r in live if r.class_type == "Batch"),
        "one":   sum(1 for r in live if r.class_type == "1-on-1"),
    }

    todo = outstanding_for(tid, days_back=7)
    timeline = day_timeline(tid, anchor) if view == "day" else None

    step = {"day": timedelta(days=1), "week": timedelta(days=7),
            "month": timedelta(days=31)}[view]
    prev_d = (start - timedelta(days=1)) if view == "month" else (anchor - step)
    next_d = (end + timedelta(days=1)) if view == "month" else (anchor + step)

    todays = [r for r in rows if r.date == today]
    if not todays and view != "day":
        todays = (ClassSchedule.query
                  .filter_by(teacher_id=tid, date=today)
                  .order_by(ClassSchedule.start_time).all())

    return render_template("teacher/my_schedule.html",
                           view=view, days=days, start=start, end=end,
                           anchor=anchor, prev_d=prev_d, next_d=next_d,
                           today=today, stats=stats, todo=todo,
                           timeline=timeline, todays=todays,
                           me=db.session.get(User, tid),
                           all_teachers=(User.query.filter_by(
                               role="TEACHER", status="ACTIVE")
                               .order_by(User.full_name).all()
                               if current_user.is_admin else []),
                           filter_tid=tid if current_user.is_admin else None)


# ──────────────────────── register and lesson notes, together ───────────────

@bp.route("/teacher/class/<int:cid>", methods=["GET", "POST"])
@login_required
@teacher_only
def class_record(cid):
    """
    One screen for a single class: who turned up, and what was taught.
    Saving does both at once.
    """
    cls = db.session.get(ClassSchedule, cid)
    if not cls:
        abort(404)
    if not current_user.is_admin and cls.teacher_id != current_user.id:
        abort(403)

    # Who should be here
    if cls.group:
        students = [m.student for m in cls.group.members if m.student]
    elif cls.student:
        students = [cls.student]
    elif cls.course_id:
        students = _my_students(cls.course_id)
    else:
        students = []
    students.sort(key=lambda s: s.full_name)

    existing = {a.student_id: a for a in
                ScheduleAttendance.query.filter_by(schedule_id=cid).all()}
    log = (LessonLog.query.filter_by(course_id=cls.course_id,
                                     class_date=cls.date).first()
           if cls.course_id else None)

    if request.method == "POST":
        marked = 0
        for s in students:
            status = request.form.get(f"status_{s.id}")
            if not status:
                continue
            rec = existing.get(s.id)
            if rec:
                rec.status = status
                rec.marked_at = datetime.utcnow()
                rec.marked_by = current_user.id
            else:
                db.session.add(ScheduleAttendance(
                    schedule_id=cid, student_id=s.id, status=status,
                    marked_by=current_user.id))
            # keep the course register in step
            if cls.course_id:
                day = Attendance.query.filter_by(
                    student_id=s.id, course_id=cls.course_id,
                    date=cls.date).first()
                val = "Present" if status in ("Present", "Late") else "Absent"
                if status == "Late":
                    val = "Late"
                if day:
                    day.status = val
                else:
                    db.session.add(Attendance(
                        student_id=s.id, course_id=cls.course_id,
                        date=cls.date, status=val))
            marked += 1

        topic = request.form.get("topic_taught", "").strip()
        if topic and cls.course_id:
            if log:
                log.topic_taught  = topic
                log.summary_notes = request.form.get("summary_notes", "").strip() or None
                log.homework      = request.form.get("homework", "").strip() or None
            else:
                db.session.add(LessonLog(
                    course_id=cls.course_id, teacher_id=cls.teacher_id,
                    class_date=cls.date, topic_taught=topic,
                    summary_notes=request.form.get("summary_notes", "").strip() or None,
                    homework=request.form.get("homework", "").strip() or None))

        # the class itself
        if students:
            all_out = all(request.form.get(f"status_{s.id}") == "Absent"
                          for s in students)
            cls.status = "Student Absent" if all_out else "Completed"
        else:
            cls.status = request.form.get("class_status", "Completed")
        db.session.commit()

        bits = []
        if marked:
            bits.append(f"attendance for {marked} student(s)")
        if topic:
            bits.append("lesson notes")
        flash("Saved " + (" and ".join(bits) if bits else "the class") + ".",
              "success")
        return redirect(url_for("teacher.my_schedule", view="day",
                                date=cls.date.isoformat()))

    return render_template("teacher/class_record.html",
                           cls=cls, students=students,
                           existing=existing, log=log)


@bp.route("/teacher/schedule.pdf")
@login_required
@teacher_only
def my_schedule_pdf():
    """The teacher's own timetable as a PDF."""
    from flask import Response
    try:
        from pdf_export import teacher_schedule_pdf
    except Exception:
        flash("PDF export needs the fpdf2 package. Run: pip install fpdf2", "danger")
        return redirect(url_for("teacher.my_schedule"))

    tid = ((request.args.get("teacher_id", type=int) if current_user.is_admin
            else None) or current_user.id)
    teacher = db.session.get(User, tid)
    if not teacher:
        abort(404)

    today = date.today()
    start = parse_date(request.args.get("start")) or (
        today - timedelta(days=today.weekday()))
    end = parse_date(request.args.get("end")) or (start + timedelta(days=6))

    rows = (ClassSchedule.query
            .filter(ClassSchedule.teacher_id == tid,
                    ClassSchedule.date >= start, ClassSchedule.date <= end)
            .order_by(ClassSchedule.date, ClassSchedule.start_time).all())
    try:
        data = teacher_schedule_pdf(teacher, rows, start, end)
    except RuntimeError:
        flash("PDF export needs the fpdf2 package.", "danger")
        return redirect(url_for("teacher.my_schedule"))
    safe = teacher.full_name.replace(" ", "_")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"attachment; filename=timetable_{safe}.pdf"})


# ─────────────────────────────────────────── submissions ────────────────────

# ─── one gate for every write on a piece of work ───────────────────────

def _may_manage_course(course_id):
    """May the signed-in teacher manage things on this subject?"""
    if current_user.is_admin:
        return True
    if not course_id:
        return False
    if ClassGroup.query.filter_by(course_id=course_id,
                                  teacher_id=current_user.id).first():
        return True
    return bool(ClassAssignment.query.filter_by(
        course_id=course_id, teacher_id=current_user.id).first())


def _may_manage(a):
    """
    May the signed-in teacher manage this piece of work?

    True when they set it, when they run a class on the subject, or when they
    are enrolled to teach it. Admins always may. Every write route on an
    assessment goes through this — the view already did, but the three write
    routes did not, which let any teacher mark another teacher's work.
    """
    if not a:
        return False
    if current_user.is_admin:
        return True
    if a.teacher_id == current_user.id:
        return True
    if ClassGroup.query.filter_by(course_id=a.course_id,
                                  teacher_id=current_user.id).first():
        return True
    return bool(ClassAssignment.query.filter_by(
        course_id=a.course_id, teacher_id=current_user.id).first())


@bp.route("/teacher/work/<int:aid>/submissions")
@login_required
@teacher_only
def submissions(aid):
    """Who has handed in, confirm receipt, then mark."""
    a = db.session.get(Assessment, aid)
    if not a:
        abort(404)
    if not _may_manage(a):
        abort(403)
    # anyone added to the subject after the work was set still needs a row,
    # and anyone who submitted without one must not be lost
    sync_assessment_rows(a)
    rows = []
    seen = set()
    for s in _my_students(a.course_id):
        r = Result.query.filter_by(assessment_id=aid, student_id=s.id).first()
        if not r:
            r = Result(assessment_id=aid, student_id=s.id)
            db.session.add(r)
        seen.add(s.id)
        rows.append({"student": s, "r": r})
    # a submission from someone outside the teacher's own classes is still a
    # submission — show it rather than hiding the work
    for r in Result.query.filter_by(assessment_id=aid).all():
        if r.student_id not in seen and r.student:
            rows.append({"student": r.student, "r": r})
    db.session.commit()
    order = {"Submitted": 0, "Received": 1, "Marked": 2, "Not Submitted": 3}
    rows.sort(key=lambda x: (order.get(x["r"].state, 9), x["student"].full_name))
    return render_template("teacher/submissions.html", a=a, rows=rows)


@bp.route("/teacher/submission/<int:rid>/received", methods=["POST"])
@login_required
@teacher_only
def confirm_received(rid):
    """
    Confirm the work is in hand.

    It does not have to have come through the portal. A student may hand in
    paper in class, email it, or bring a notebook — the teacher records that
    they have it, with a note saying how, and marking opens up.
    """
    r = db.session.get(Result, rid)
    if not r:
        abort(404)
    if not _may_manage(r.assessment):
        abort(403)
    if request.form.get("undo") == "1":
        r.received, r.received_at = False, None
        r.received_by, r.received_note = None, None
        db.session.commit()
        flash("Receipt withdrawn. Marking is locked again.", "info")
        return redirect(url_for("teacher.submissions", aid=r.assessment_id))

    note = (request.form.get("received_note") or "").strip()
    if not r.via_portal and not note:
        note = "Handed in outside the portal"
    r.received = True
    r.received_at = datetime.utcnow()
    r.received_by = current_user.id
    r.received_note = note[:255] or None
    db.session.commit()
    log_action("work-received",
               f"{r.assessment.title}: {r.student.full_name}"
               + (f" ({note})" if note else ""))
    flash(f"Receipt confirmed for {r.student.full_name}. "
          f"You can enter marks now.", "success")
    return redirect(url_for("teacher.submissions", aid=r.assessment_id))


@bp.route("/teacher/work/<int:aid>/received-all", methods=["POST"])
@login_required
@teacher_only
def receive_all(aid):
    """Everyone handed something in — a stack of papers collected in class."""
    a = db.session.get(Assessment, aid)
    if not a:
        abort(404)
    if not _may_manage(a):
        abort(403)
    note = (request.form.get("received_note") or "Collected in class").strip()
    n = 0
    for r in Result.query.filter_by(assessment_id=aid).all():
        if r.received or r.score is not None:
            continue
        r.received = True
        r.received_at = datetime.utcnow()
        r.received_by = current_user.id
        r.received_note = note[:255]
        n += 1
    db.session.commit()
    log_action("work-received", f"{a.title}: {n} marked as received ({note})")
    flash(f"{n} student(s) recorded as handed in. You can mark them now."
          if n else "Everyone was already recorded.", "success" if n else "info")
    return redirect(url_for("teacher.submissions", aid=aid))


@bp.route("/teacher/submission/<int:rid>/mark", methods=["POST"])
@login_required
@teacher_only
def mark_one(rid):
    """Mark a single submission, only once receipt is confirmed."""
    r = db.session.get(Result, rid)
    if not r:
        abort(404)
    if not _may_manage(r.assessment):
        abort(403)
    if not r.can_mark:
        flash("Tick that you have the work before marking it — "
              "or set the work so it does not need handing in.", "danger")
        return redirect(url_for("teacher.submissions", aid=r.assessment_id))
    raw = request.form.get("score", "").strip()
    if raw:
        try:
            val = float(raw)
        except ValueError:
            flash("That is not a valid mark.", "danger")
            return redirect(url_for("teacher.submissions", aid=r.assessment_id))
        if val < 0 or val > (r.assessment.max_score or 100):
            flash(f"The mark must be between 0 and "
                  f"{r.assessment.max_score:g}.", "danger")
            return redirect(url_for("teacher.submissions", aid=r.assessment_id))
        r.score = val
        r.marked_at = datetime.utcnow()
    fb = request.form.get("feedback", "").strip()
    if fb:
        r.feedback = fb
    db.session.commit()
    flash(f"Marked {r.student.full_name}.", "success")
    return redirect(url_for("teacher.submissions", aid=r.assessment_id))


@bp.route("/teacher/file/assignment/<int:aid>")
@login_required
@teacher_only
def download_brief(aid):
    a = db.session.get(Assessment, aid)
    if not a or not a.attachment_key:
        abort(404)
    if not _may_manage(a):
        abort(403)
    p = upload_path(a.attachment_key)
    if not p:
        abort(404)
    return send_file(p, as_attachment=True, download_name=a.attachment_name)


@bp.route("/teacher/file/submission/<int:rid>")
@login_required
@teacher_only
def download_submission(rid):
    """Only for a teacher who may manage that course."""
    r = db.session.get(Result, rid)
    if not r or not r.file_key:
        abort(404)
    if not _may_manage(r.assessment):
        abort(403)
    p = upload_path(r.file_key)
    if not p:
        abort(404)
    return send_file(p, as_attachment=True, download_name=r.file_name)
