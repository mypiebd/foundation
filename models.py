"""Database models for PIE Pathways."""

from datetime import date, datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

BRANCHES = ["Banani", "Dhanmondi", "Siddeshwari", "Uttara"]
ASSESSMENT_KINDS = ["Assignment", "Practice work", "Homework", "Quiz", "Mock exam", "Exam"]
ATTENDANCE_STATUSES = ["Present", "Late", "Absent"]


class User(UserMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(16), nullable=False, index=True)  # ADMIN|TEACHER|STUDENT
    status = db.Column(db.String(16), default="ACTIVE", nullable=False, index=True)  # ACTIVE|ARCHIVED
    phone = db.Column(db.String(32))
    email = db.Column(db.String(120))
    branch = db.Column(db.String(32), index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), index=True)
    initial_password = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    batch = db.relationship("Batch", backref="students")

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    # Flask-Login uses this to decide whether a session may be created.
    @property
    def is_active(self):
        return self.status == "ACTIVE"

    @property
    def is_archived(self):
        return self.status == "ARCHIVED"

    @property
    def is_admin(self):
        return self.role == "ADMIN"

    @property
    def is_teacher(self):
        return self.role == "TEACHER"

    @property
    def is_student(self):
        return self.role == "STUDENT"

    def __repr__(self):
        return f"<User {self.username} {self.role}>"


class Batch(db.Model):
    """An intake, e.g. 'IFY January 2026'. Students belong to one."""
    __tablename__ = "batch"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    branch = db.Column(db.String(32))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def active_students(self):
        return [s for s in self.students if s.status == "ACTIVE"]


class Term(db.Model):
    """A named date range. Reports filter attendance and marks by it."""
    __tablename__ = "term"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)

    def covers(self, day):
        return self.start_date <= day <= self.end_date


class Course(db.Model):
    __tablename__ = "course"
    id = db.Column(db.Integer, primary_key=True)
    course_code = db.Column(db.String(32), unique=True, nullable=False)
    course_name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    branch = db.Column(db.String(32))
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<Course {self.course_code}>"


class ClassAssignment(db.Model):
    """One student, in one course, under one teacher."""
    __tablename__ = "class_assignment"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    course = db.relationship("Course", backref=db.backref("assignments", cascade="all, delete-orphan"))
    teacher = db.relationship("User", foreign_keys=[teacher_id],
                              backref=db.backref("teaching_assignments",
                                                 cascade="all, delete-orphan"))
    student = db.relationship("User", foreign_keys=[student_id],
                              backref=db.backref("enrolments",
                                                 cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint("course_id", "student_id", name="uq_course_student"),)


class TeacherOffDay(db.Model):
    __tablename__ = "teacher_off_day"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    off_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(160))

    teacher = db.relationship("User", backref=db.backref("off_days", cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint("teacher_id", "off_date", name="uq_teacher_offday"),)


class CourseMaterial(db.Model):
    __tablename__ = "course_material"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    file_path_or_link = db.Column(db.Text, nullable=False)
    is_link = db.Column(db.Boolean, default=False, nullable=False)
    file_size = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship("Course", backref=db.backref("materials", cascade="all, delete-orphan"))
    teacher = db.relationship("User", backref=db.backref("uploaded_materials", cascade="all, delete-orphan"))


class LessonLog(db.Model):
    __tablename__ = "lesson_log"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    class_date = db.Column(db.Date, nullable=False, index=True)
    topic_taught = db.Column(db.Text, nullable=False)
    summary_notes = db.Column(db.Text)

    course = db.relationship("Course", backref=db.backref("lessons", cascade="all, delete-orphan"))
    teacher = db.relationship("User", backref=db.backref("teacher_lessons", cascade="all, delete-orphan"))


class Attendance(db.Model):
    __tablename__ = "attendance"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False)

    student = db.relationship("User", backref=db.backref("attendance_records", cascade="all, delete-orphan"))
    course = db.relationship("Course", backref=db.backref("attendance_records", cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint("student_id", "course_id", "date", name="uq_attendance_day"),)


class Assessment(db.Model):
    """A piece of work: assignment, practice, quiz, mock or exam."""
    __tablename__ = "assessment"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(32), default="Assignment", nullable=False)
    instructions = db.Column(db.Text)
    attachment_link = db.Column(db.Text)      # Drive / YouTube / any URL
    assigned_date = db.Column(db.Date, default=date.today, nullable=False)
    due_date = db.Column(db.Date)
    max_score = db.Column(db.Float, default=100.0, nullable=False)
    needs_submission = db.Column(db.Boolean, default=True, nullable=False)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship("Course", backref=db.backref("assessments", cascade="all, delete-orphan"))
    teacher = db.relationship("User", backref=db.backref("assessments_set", cascade="all, delete-orphan"))

    @property
    def is_overdue(self):
        return bool(self.due_date and self.due_date < date.today())


class Result(db.Model):
    """One student's submission and mark for one assessment."""
    __tablename__ = "result"
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessment.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    submission_link = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime)
    score = db.Column(db.Float)
    feedback = db.Column(db.Text)
    marked_at = db.Column(db.DateTime)

    assessment = db.relationship("Assessment", backref=db.backref("results", cascade="all, delete-orphan"))
    student = db.relationship("User", backref=db.backref("results", cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint("assessment_id", "student_id", name="uq_result"),)

    @property
    def percent(self):
        if self.score is None or not self.assessment.max_score:
            return None
        return round(self.score / self.assessment.max_score * 100, 1)

    @property
    def state(self):
        if self.score is not None:
            return "Marked"
        if self.submitted_at:
            return "Submitted"
        return "Not submitted"


class Announcement(db.Model):
    """A notice. Admins post to everyone or to a branch/batch; teachers post to
    one of their courses."""
    __tablename__ = "announcement"
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), index=True)  # None = general
    branch = db.Column(db.String(32))        # admin targeting, None = all branches
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"))   # None = all batches
    audience = db.Column(db.String(16), default="STUDENTS", nullable=False)  # STUDENTS|TEACHERS|EVERYONE
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    is_urgent = db.Column(db.Boolean, default=False, nullable=False)
    expires_on = db.Column(db.Date)          # None = stays until deleted
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    author = db.relationship("User", backref=db.backref("announcements",
                                                        cascade="all, delete-orphan"))
    course = db.relationship("Course", backref=db.backref("announcements",
                                                          cascade="all, delete-orphan"))
    batch = db.relationship("Batch")

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
        if self.batch:
            bits.append(self.batch.name)
        return " · ".join(bits) if bits else "Everyone"


class AuditLog(db.Model):
    """Who changed a mark, and when."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(64), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship("User")
