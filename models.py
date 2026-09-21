"""PIE Scheduler — database models."""
from datetime import date, datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def fmt_time(t):
    """4:00 PM rather than 16:00 — used everywhere on screen."""
    return t.strftime("%I:%M %p").lstrip("0") if t else ""

BRANCHES = ["Banani", "Dhanmondi", "Siddeshwari", "Uttara"]
COURSES_LIST = ["IELTS", "PTE", "GED Math", "GED RLA", "GED Science",
                "GED S.S", "SAT Math", "SAT English", "Basic English", "EAP", "Other"]
ASSESSMENT_KINDS = ["Assignment", "Homework", "Practice work", "Quiz", "Mock exam", "Exam"]
ATTENDANCE_STATUSES = ["Present", "Late", "Absent"]


class User(UserMixin, db.Model):
    __tablename__ = "user"
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash= db.Column(db.String(255), nullable=False)
    full_name    = db.Column(db.String(120), nullable=False)
    role         = db.Column(db.String(16), nullable=False, index=True)
    # ADMIN | TEACHER | STUDENT | STUDENT_VIEWER
    status       = db.Column(db.String(16), default="ACTIVE", nullable=False, index=True)
    phone        = db.Column(db.String(32))
    email        = db.Column(db.String(120))
    branch       = db.Column(db.String(32), index=True)
    subjects     = db.Column(db.String(255))          # teachers only
    max_daily_hours = db.Column(db.Float, default=8.0)# teachers only
    days_off     = db.Column(db.String(32))           # teachers: "0,3" = Mon,Thu
    work_hours   = db.Column(db.String(255))          # "0=10:00-20:00;1=14:00-20:00"
    initial_password = db.Column(db.String(64))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def is_active(self):
        return self.status == "ACTIVE"

    @property
    def is_admin(self):
        return self.role == "ADMIN"

    @property
    def is_teacher(self):
        return self.role == "TEACHER"

    @property
    def is_student(self):
        return self.role == "STUDENT"

    @property
    def is_viewer(self):
        """Front-desk account: may look, may never touch."""
        return self.role == "STUDENT_VIEWER"

    @property
    def can_write(self):
        return self.role in ("ADMIN", "TEACHER")

    @property
    def off_days(self):
        """Python weekday numbers this teacher does not work. Mon=0 ... Sun=6."""
        if not self.days_off:
            return set()
        return {int(x) for x in self.days_off.split(",") if x.strip().isdigit()}

    @property
    def off_days_label(self):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        off = sorted(self.off_days)
        return ", ".join(names[d] for d in off) if off else "None"

    @property
    def working_days_label(self):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        off = self.off_days
        on = [names[d] for d in range(7) if d not in off]
        return ", ".join(on) if on else "None"

    @property
    def hours_map(self):
        """weekday -> (start, end) for the days this teacher works."""
        from datetime import time as _t
        out = {}
        if not self.work_hours:
            return out
        for chunk in self.work_hours.split(";"):
            if "=" not in chunk:
                continue
            day, span = chunk.split("=", 1)
            if "-" not in span or not day.strip().isdigit():
                continue
            a, b = span.split("-", 1)
            try:
                ah, am = [int(x) for x in a.strip().split(":")]
                bh, bm = [int(x) for x in b.strip().split(":")]
                out[int(day)] = (_t(ah, am), _t(bh, bm))
            except ValueError:
                continue
        return out

    def hours_on(self, d):
        """(start, end) the teacher is available that day, or None."""
        wd = d.weekday() if hasattr(d, "weekday") else d
        if wd in self.off_days:
            return None
        return self.hours_map.get(wd)

    @property
    def hours_label(self):
        m = self.hours_map
        if not m:
            return "Not set"
        f = lambda t: t.strftime("%I:%M %p").lstrip("0")
        spans = {}
        for wd, (a, b) in m.items():
            spans.setdefault((a, b), []).append(wd)
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        order = [5, 6, 0, 1, 2, 3, 4]
        parts = []
        for (a, b), days in sorted(spans.items(), key=lambda x: min(x[1])):
            ds = sorted(days, key=lambda d: order.index(d))
            parts.append(f"{', '.join(names[d] for d in ds)} {f(a)}-{f(b)}")
        return "   ".join(parts)

    def works_on(self, d):
        return d.weekday() not in self.off_days

    def __repr__(self):
        return f"<User {self.username} {self.role}>"



class Term(db.Model):
    __tablename__ = "term"
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), unique=True, nullable=False)
    start_date   = db.Column(db.Date, nullable=False)
    end_date     = db.Column(db.Date, nullable=False)
    is_current   = db.Column(db.Boolean, default=False, nullable=False)

    def covers(self, day):
        return self.start_date <= day <= self.end_date


class Course(db.Model):
    __tablename__ = "course"
    id           = db.Column(db.Integer, primary_key=True)
    course_code  = db.Column(db.String(32), unique=True, nullable=False)
    course_name  = db.Column(db.String(160), nullable=False)
    description  = db.Column(db.Text)          # what the course is, in prose
    # all optional — each is shown only when filled in
    mnemonic       = db.Column(db.String(40))    # e.g. 03 IFY MDH
    awarding_body  = db.Column(db.String(120))   # e.g. INTO Qualifications
    level          = db.Column(db.String(80))    # e.g. RQF Level 3
    credits        = db.Column(db.Integer)
    learning_hours = db.Column(db.Integer)
    assessment     = db.Column(db.Text)          # one line per component
    outcomes       = db.Column(db.Text)          # one line per outcome
    branch       = db.Column(db.String(32))
    is_archived  = db.Column(db.Boolean, default=False, nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def assessment_lines(self):
        return [l.strip() for l in (self.assessment or "").splitlines() if l.strip()]

    @property
    def outcome_lines(self):
        return [l.strip() for l in (self.outcomes or "").splitlines() if l.strip()]

    @property
    def has_detail(self):
        """Is there anything worth showing beyond the name?"""
        return bool(self.description or self.assessment or self.outcomes
                    or self.credits or self.learning_hours)

    @property
    def facts(self):
        """Short labelled facts for the header strip."""
        out = []
        if self.mnemonic:      out.append(("Module code", self.mnemonic))
        if self.awarding_body: out.append(("Awarded by", self.awarding_body))
        if self.level:         out.append(("Level", self.level))
        if self.credits:       out.append(("Credits", str(self.credits)))
        if self.learning_hours:
            out.append(("Learning hours", str(self.learning_hours)))
        return out

    def __repr__(self):
        return f"<Course {self.course_code}>"


class ClassAssignment(db.Model):
    """One student enrolled in one course under one teacher."""
    __tablename__ = "class_assignment"
    id         = db.Column(db.Integer, primary_key=True)
    course_id  = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    course  = db.relationship("Course", backref=db.backref("assignments", cascade="all, delete-orphan"))
    teacher = db.relationship("User", foreign_keys=[teacher_id],
                              backref=db.backref("teaching_assignments", cascade="all, delete-orphan"))
    student = db.relationship("User", foreign_keys=[student_id],
                              backref=db.backref("enrolments", cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint("course_id", "student_id", name="uq_course_student"),)


class ClassSchedule(db.Model):
    """A single scheduled class slot — 1-on-1 or batch."""
    __tablename__ = "class_schedule"
    id           = db.Column(db.Integer, primary_key=True)
    date         = db.Column(db.Date, nullable=False, index=True)
    start_time   = db.Column(db.Time, nullable=False)
    end_time     = db.Column(db.Time, nullable=False)
    duration_mins= db.Column(db.Integer, nullable=False)
    task         = db.Column(db.String(200))
    class_type   = db.Column(db.String(20), nullable=False, default="1-on-1")
    venue        = db.Column(db.String(80), default="Centre")
    room         = db.Column(db.String(100))          # typed per date by admin
    teacher_id   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    course_id    = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=True)
    student_id   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    status       = db.Column(db.String(30), default="Scheduled", index=True)
    notes        = db.Column(db.Text)
    group_id     = db.Column(db.Integer, db.ForeignKey("class_group.id"), index=True)
    slot_id      = db.Column(db.Integer, db.ForeignKey("class_slot.id"))
    created_by   = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    teacher = db.relationship("User", foreign_keys=[teacher_id],
                              backref=db.backref("teacher_schedules", cascade="all, delete-orphan"))
    student = db.relationship("User", foreign_keys=[student_id],
                              backref=db.backref("student_schedules", lazy="dynamic"))
    course  = db.relationship("Course", backref=db.backref("schedules", cascade="all, delete-orphan"))
    att_records = db.relationship("ScheduleAttendance", backref="schedule",
                                  cascade="all, delete-orphan")

    @property
    def start_str(self):
        return self.start_time.strftime("%I:%M %p")

    @property
    def end_str(self):
        return self.end_time.strftime("%I:%M %p")

    @property
    def room_label(self):
        """What to print. ONLINE wins over a typed room."""
        if (self.venue or "").strip().lower() in ("online", "zoom"):
            return "ONLINE"
        return (self.room or "").strip() or "TBA"

    @property
    def head_count(self):
        """Students actually attached to this occurrence, never a course total."""
        from models import GroupStudent
        if self.group_id:
            return GroupStudent.query.filter_by(group_id=self.group_id).count()
        if self.student_id:
            return 1
        return None

    @property
    def start_mins(self):
        return self.start_time.hour * 60 + self.start_time.minute

    @property
    def end_mins(self):
        return self.end_time.hour * 60 + self.end_time.minute


class ScheduleAttendance(db.Model):
    """Attendance for a specific scheduled class slot."""
    __tablename__ = "schedule_attendance"
    id           = db.Column(db.Integer, primary_key=True)
    schedule_id  = db.Column(db.Integer, db.ForeignKey("class_schedule.id"), nullable=False, index=True)
    student_id   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status       = db.Column(db.String(20), nullable=False, default="Present")
    marked_by    = db.Column(db.Integer, db.ForeignKey("user.id"))
    marked_at    = db.Column(db.DateTime, default=datetime.utcnow)
    remarks      = db.Column(db.Text)

    student = db.relationship("User", foreign_keys=[student_id],
                              backref=db.backref("schedule_attendances", lazy="dynamic"))

    __table_args__ = (db.UniqueConstraint("schedule_id", "student_id", name="uq_sched_att"),)


class Attendance(db.Model):
    """Course register attendance — teacher marks per date."""
    __tablename__ = "attendance"
    id         = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    course_id  = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    date       = db.Column(db.Date, nullable=False, index=True)
    status     = db.Column(db.String(16), nullable=False)

    student = db.relationship("User", backref=db.backref("attendance_records",
                                                          cascade="all, delete-orphan"))
    course  = db.relationship("Course", backref=db.backref("attendance_records",
                                                            cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint("student_id", "course_id", "date",
                                          name="uq_attendance_day"),)


class LessonLog(db.Model):
    """Teacher's post-class notes."""
    __tablename__ = "lesson_log"
    id           = db.Column(db.Integer, primary_key=True)
    course_id    = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    teacher_id   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    class_date   = db.Column(db.Date, nullable=False, index=True)
    topic_taught = db.Column(db.Text, nullable=False)
    summary_notes= db.Column(db.Text)
    homework     = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    course  = db.relationship("Course", backref=db.backref("lessons",
                                                            cascade="all, delete-orphan"))
    teacher = db.relationship("User", backref=db.backref("teacher_lessons",
                                                          cascade="all, delete-orphan"))


class Assessment(db.Model):
    """Homework, quiz, mock or exam set by a teacher."""
    __tablename__ = "assessment"
    id              = db.Column(db.Integer, primary_key=True)
    course_id       = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    teacher_id      = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title           = db.Column(db.String(160), nullable=False)
    kind            = db.Column(db.String(32), default="Assignment", nullable=False)
    instructions    = db.Column(db.Text)
    attachment_link = db.Column(db.Text)
    assigned_date   = db.Column(db.Date, default=date.today, nullable=False)
    due_date        = db.Column(db.Date)
    max_score       = db.Column(db.Float, default=100.0, nullable=False)
    needs_submission= db.Column(db.Boolean, default=True, nullable=False)
    is_published    = db.Column(db.Boolean, default=True, nullable=False)
    # teacher's attached brief
    attachment_name = db.Column(db.String(255))
    attachment_key  = db.Column(db.String(255))
    attachment_mime = db.Column(db.String(120))
    attachment_size = db.Column(db.Integer)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def has_file(self):
        return bool(self.attachment_key)

    course  = db.relationship("Course", backref=db.backref("assessments",
                                                            cascade="all, delete-orphan"))
    teacher = db.relationship("User", backref=db.backref("assessments_set",
                                                          cascade="all, delete-orphan"))

    @property
    def is_overdue(self):
        return bool(self.due_date and self.due_date < date.today())


class Result(db.Model):
    """Student submission and mark for one assessment."""
    __tablename__ = "result"
    id              = db.Column(db.Integer, primary_key=True)
    assessment_id   = db.Column(db.Integer, db.ForeignKey("assessment.id"),
                                nullable=False, index=True)
    student_id      = db.Column(db.Integer, db.ForeignKey("user.id"),
                                nullable=False, index=True)
    submission_link = db.Column(db.Text)
    submitted_at    = db.Column(db.DateTime)
    # uploaded work
    file_name       = db.Column(db.String(255))
    file_key        = db.Column(db.String(255))
    file_mime       = db.Column(db.String(120))
    file_size       = db.Column(db.Integer)
    student_note    = db.Column(db.Text)
    # teacher acknowledges receipt before marking
    received        = db.Column(db.Boolean, default=False, nullable=False)
    received_at     = db.Column(db.DateTime)
    received_by     = db.Column(db.Integer, db.ForeignKey("user.id"))
    # how the teacher got it when nothing came through the portal
    received_note   = db.Column(db.String(255))
    score           = db.Column(db.Float)
    feedback        = db.Column(db.Text)
    marked_at       = db.Column(db.DateTime)

    assessment = db.relationship("Assessment", backref=db.backref("results",
                                                                   cascade="all, delete-orphan"))
    student    = db.relationship("User", foreign_keys=[student_id],
                                 backref=db.backref("results",
                                                             cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint("assessment_id", "student_id", name="uq_result"),)

    @property
    def percent(self):
        if self.score is None or not self.assessment.max_score:
            return None
        return round(self.score / self.assessment.max_score * 100, 1)

    @property
    def has_file(self):
        return bool(self.file_key)

    @property
    def state(self):
        """Not Submitted -> Submitted -> Received -> Marked."""
        if self.score is not None:
            return "Marked"
        if self.received:
            return "Received"
        if self.submitted_at or self.file_key or self.submission_link:
            return "Submitted"
        return "Not Submitted"

    @property
    def via_portal(self):
        """Did the student actually upload or link something?"""
        return bool(self.file_key or self.submission_link)

    @property
    def can_mark(self):
        """
        Marking is open when the work does not need handing in at all — a
        test, a mock, an in-class task — or when the teacher has confirmed
        they have it, whether it arrived through the portal or on paper.
        """
        if self.assessment and not self.assessment.needs_submission:
            return True
        return bool(self.received)


class CourseMaterial(db.Model):
    __tablename__ = "course_material"
    id               = db.Column(db.Integer, primary_key=True)
    course_id        = db.Column(db.Integer, db.ForeignKey("course.id"),
                                 nullable=False, index=True)
    teacher_id       = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title            = db.Column(db.String(200), nullable=False)
    file_path_or_link= db.Column(db.Text, nullable=False)
    is_link          = db.Column(db.Boolean, default=False, nullable=False)
    file_size        = db.Column(db.Integer, default=0)
    uploaded_at      = db.Column(db.DateTime, default=datetime.utcnow)

    course  = db.relationship("Course", backref=db.backref("materials",
                                                            cascade="all, delete-orphan"))
    teacher = db.relationship("User", backref=db.backref("uploaded_materials",
                                                          cascade="all, delete-orphan"))


class Announcement(db.Model):
    __tablename__ = "announcement"
    id         = db.Column(db.Integer, primary_key=True)
    author_id  = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    course_id  = db.Column(db.Integer, db.ForeignKey("course.id"), index=True)
    branch     = db.Column(db.String(32))
    audience   = db.Column(db.String(16), default="STUDENTS", nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    body       = db.Column(db.Text)
    is_urgent  = db.Column(db.Boolean, default=False, nullable=False)
    expires_on = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    author = db.relationship("User", backref=db.backref("announcements",
                                                         cascade="all, delete-orphan"))
    course = db.relationship("Course", backref=db.backref("announcements",
                                                           cascade="all, delete-orphan"))

    @property
    def is_expired(self):
        return bool(self.expires_on and self.expires_on < date.today())

    @property
    def scope(self):
        if self.course_id:
            return self.course.course_code
        bits = []
        if self.branch:
            bits.append(self.branch)
        return " · ".join(bits) if bits else "Everyone"


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id         = db.Column(db.Integer, primary_key=True)
    actor_id   = db.Column(db.Integer, db.ForeignKey("user.id"))
    action     = db.Column(db.String(64), nullable=False)
    detail     = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship("User")


class ClassGroup(db.Model):
    """
    One teaching arrangement: a subject, a teacher, the students, and the
    times it runs. A batch and a one-to-one are the same object with a
    different kind, so GED Social Studies can be taught both ways without
    inventing two courses.
    """
    __tablename__ = "class_group"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    kind        = db.Column(db.String(20), nullable=False, default="Batch")  # Batch | 1-on-1
    course_id   = db.Column(db.Integer, db.ForeignKey("course.id"), index=True)
    teacher_id  = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    venue       = db.Column(db.String(80), default="Centre")

    start_date  = db.Column(db.Date, nullable=False)
    end_date    = db.Column(db.Date)            # None = runs until stopped
    generated_to= db.Column(db.Date)

    status      = db.Column(db.String(20), default="Active", index=True)
    pause_from  = db.Column(db.Date)
    pause_to    = db.Column(db.Date)
    note        = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    course   = db.relationship("Course", backref="groups")
    teacher  = db.relationship("User", foreign_keys=[teacher_id])
    slots    = db.relationship("ClassSlot", backref="group",
                               cascade="all, delete-orphan",
                               order_by="ClassSlot.weekday, ClassSlot.start_time")
    members  = db.relationship("GroupStudent", backref="group",
                               cascade="all, delete-orphan")
    sessions = db.relationship("ClassSchedule", backref="group",
                               cascade="all, delete-orphan", lazy="dynamic")

    @property
    def students(self):
        return [m.student for m in self.members if m.student]

    @property
    def student_count(self):
        # only people who still exist — a stale membership must not inflate it
        return sum(1 for m in self.members if m.student is not None)

    @property
    def is_indefinite(self):
        return self.end_date is None

    @property
    def days_label(self):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        order = [5, 6, 0, 1, 2, 3, 4]
        got = sorted({s.weekday for s in self.slots},
                     key=lambda d: order.index(d) if d in order else 9)
        return ", ".join(names[d] for d in got) if got else "No days set"

    @property
    def times_label(self):
        """One line per distinct time, or a single line when they all match."""
        if not self.slots:
            return "No times set"
        spans = {(s.start_time, s.end_time) for s in self.slots}
        if len(spans) == 1:
            a, b = spans.pop()
            return f"{fmt_time(a)} - {fmt_time(b)}"
        return f"{len(spans)} different times"

    @property
    def slot_lines(self):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        order = [5, 6, 0, 1, 2, 3, 4]
        out = []
        for s in sorted(self.slots,
                        key=lambda x: (order.index(x.weekday)
                                       if x.weekday in order else 9, x.start_time)):
            out.append(f"{names[s.weekday]} {fmt_time(s.start_time)}"
                       f" - {fmt_time(s.end_time)}")
        return out

    def paused_on(self, d):
        if self.status != "Paused":
            return False
        if self.pause_from and d < self.pause_from:
            return False
        if self.pause_to and d > self.pause_to:
            return False
        return True

    def counts(self):
        from datetime import date as _d
        today = _d.today()
        all_s = self.sessions.all()
        return {
            "total":     len(all_s),
            "past":      sum(1 for s in all_s if s.date < today),
            "upcoming":  sum(1 for s in all_s
                             if s.date >= today and s.status == "Scheduled"),
            "cancelled": sum(1 for s in all_s if s.status == "Cancelled"),
        }

    def __repr__(self):
        return f"<ClassGroup {self.name}>"


class ClassSlot(db.Model):
    """One weekly time this group meets. A group may have several."""
    __tablename__ = "class_slot"
    id         = db.Column(db.Integer, primary_key=True)
    group_id   = db.Column(db.Integer, db.ForeignKey("class_group.id"),
                           nullable=False, index=True)
    weekday    = db.Column(db.Integer, nullable=False)     # Mon=0 ... Sun=6
    start_time = db.Column(db.Time, nullable=False)
    end_time   = db.Column(db.Time, nullable=False)

    @property
    def duration_mins(self):
        return ((self.end_time.hour * 60 + self.end_time.minute) -
                (self.start_time.hour * 60 + self.start_time.minute))

    @property
    def day_name(self):
        return ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"][self.weekday]

    @property
    def label(self):
        return (f"{self.day_name[:3]} {fmt_time(self.start_time)}"
                f" - {fmt_time(self.end_time)}")


class GroupStudent(db.Model):
    __tablename__ = "group_student"
    id         = db.Column(db.Integer, primary_key=True)
    group_id   = db.Column(db.Integer, db.ForeignKey("class_group.id"),
                           nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"),
                           nullable=False, index=True)
    joined_at  = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("User", foreign_keys=[student_id])

    __table_args__ = (db.UniqueConstraint("group_id", "student_id",
                                          name="uq_group_student"),)


class TeacherBlock(db.Model):
    """
    Time kept clear for a teacher — Friday prayer, a standing lunch, anything
    else. Nothing can be booked over it.
    """
    __tablename__ = "teacher_block"
    id         = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"),
                           nullable=False, index=True)
    label      = db.Column(db.String(120), nullable=False, default="Break")
    weekday    = db.Column(db.Integer)          # None = every working day
    start_time = db.Column(db.Time, nullable=False)
    end_time   = db.Column(db.Time, nullable=False)
    on_date    = db.Column(db.Date)             # set for a one-off block
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    teacher = db.relationship("User", backref=db.backref(
        "blocks", cascade="all, delete-orphan"))

    def applies_on(self, d):
        if self.on_date:
            return self.on_date == d
        if self.weekday is None:
            return True
        return d.weekday() == self.weekday

    @property
    def day_label(self):
        if self.on_date:
            return self.on_date.strftime("%d %b %Y")
        if self.weekday is None:
            return "Every working day"
        return ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"][self.weekday]

    @property
    def time_label(self):
        return f"{fmt_time(self.start_time)} - {fmt_time(self.end_time)}"
