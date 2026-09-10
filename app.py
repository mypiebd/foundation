"""PIE Pathways — application setup, authentication and first-run seeding."""

import os
from datetime import date, datetime, timedelta

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_login import (LoginManager, current_user, login_required, login_user,
                         logout_user)

from helpers import human_size, storage_usage
from models import (Batch, BRANCHES, ClassAssignment, Course, CourseMaterial,
                    LessonLog, Term, User, db)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("LMS_SECRET_KEY", "pie-pathways-change-this-key"),
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE_DIR, "lms.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,          # 5 MB per uploaded file
    UPLOAD_FOLDER=UPLOAD_DIR,
    STORAGE_BUDGET=250 * 1024 * 1024,            # amber warning above this
    STORAGE_HARD_LIMIT=350 * 1024 * 1024,        # uploads refused above this
    ORG_NAME="PIE Pathways",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Sign in to continue."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def page_args():
    """Current query string minus the page number, for pagination links."""
    args = request.args.to_dict()
    args.pop("page", None)
    return args


@app.context_processor
def inject_globals():
    return {
        "page_args": page_args,
        "today_str": date.today().isoformat(),
        "today": date.today(),
        "BRANCHES": BRANCHES,
        "human_size": human_size,
        "org_name": app.config["ORG_NAME"],
    }


# ------------------------------------------------------------- auth --------

@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(request.form.get("password", "")):
            if user.is_archived:
                flash("This account has been archived. Contact the office.", "danger")
                return redirect(url_for("login"))
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("That username and password don't match.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You're signed out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for("admin.overview"))
    if current_user.is_teacher:
        return redirect(url_for("teacher.my_courses"))
    return redirect(url_for("student.dashboard"))


@app.route("/change-password", methods=["POST"])
@login_required
def change_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not current_user.check_password(current):
        flash("Your current password is wrong.", "danger")
    elif len(new) < 6:
        flash("Use at least 6 characters for the new password.", "danger")
    elif new != confirm:
        flash("The two new passwords don't match.", "danger")
    else:
        current_user.set_password(new)
        current_user.initial_password = None
        db.session.commit()
        flash("Password changed.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/materials/<int:material_id>/open")
@login_required
def open_material(material_id):
    item = db.session.get(CourseMaterial, material_id)
    if not item:
        abort(404)
    if current_user.is_student:
        enrolled = ClassAssignment.query.filter_by(
            course_id=item.course_id, student_id=current_user.id).first()
        if not enrolled:
            abort(403)
    elif current_user.is_teacher:
        mine = {a.course_id for a in current_user.teaching_assignments}
        if item.course_id not in mine:
            abort(403)
    if item.is_link:
        return redirect(item.file_path_or_link)
    return send_from_directory(app.config["UPLOAD_FOLDER"],
                               item.file_path_or_link, as_attachment=True)


# ----------------------------------------------------------- errors --------

@app.errorhandler(401)
def unauthorised(_):
    return redirect(url_for("login"))


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code="403",
                           message="That page belongs to a different role."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code="404",
                           message="Nothing lives at that address."), 404


@app.errorhandler(413)
def too_large(_):
    flash("That file is over the 5 MB limit. Share it as a link instead.", "danger")
    return redirect(request.referrer or url_for("dashboard"))


# ------------------------------------------------------------- seed --------

def seed():
    db.create_all()
    if User.query.first():
        return

    admin = User(username="admin", full_name="System Administrator",
                 role="ADMIN", initial_password="admin123")
    admin.set_password("admin123")
    db.session.add(admin)

    today = date.today()
    term = Term(name=f"Term 1 {today.year}", start_date=today.replace(month=1, day=1),
                end_date=today.replace(month=12, day=31), is_current=True)
    batch = Batch(name=f"IFY {today.strftime('%B %Y')}", branch="Banani",
                  start_date=today, end_date=today + timedelta(days=270))
    db.session.add_all([term, batch])
    db.session.commit()

    teacher = User(username="teacher1", full_name="Rezaul Karim", role="TEACHER",
                   branch="Banani", phone="+8801700000000", initial_password="teacher123")
    teacher.set_password("teacher123")
    s1 = User(username="1001", full_name="Ayesha Rahman", role="STUDENT",
              branch="Banani", phone="+8801711111111", batch_id=batch.id,
              initial_password="student123")
    s1.set_password("student123")
    s2 = User(username="1002", full_name="Tanvir Ahmed", role="STUDENT",
              branch="Banani", phone="+8801722222222", batch_id=batch.id,
              initial_password="student123")
    s2.set_password("student123")
    db.session.add_all([teacher, s1, s2])
    db.session.commit()

    c1 = Course(course_code="EAP101", course_name="English for Academic Purposes",
                description="Reading, writing, listening and speaking for university study.",
                branch="Banani")
    c2 = Course(course_code="MTH101", course_name="Mathematics and Data Handling",
                description="Algebra, functions, statistics and data interpretation.",
                branch="Banani")
    db.session.add_all([c1, c2])
    db.session.commit()

    for course in (c1, c2):
        for student in (s1, s2):
            db.session.add(ClassAssignment(course_id=course.id, teacher_id=teacher.id,
                                           student_id=student.id))
    db.session.add(LessonLog(course_id=c1.id, teacher_id=teacher.id, class_date=today,
                             topic_taught="Class 1 — Academic paragraph structure",
                             summary_notes="Topic sentence, supporting detail, conclusion. "
                                           "Homework: draft one paragraph."))
    db.session.commit()


# Blueprints are imported here, after app and db exist, to avoid a circular import.
from views_admin import bp as admin_bp        # noqa: E402
from views_student import bp as student_bp    # noqa: E402
from views_teacher import bp as teacher_bp    # noqa: E402

app.register_blueprint(admin_bp)
app.register_blueprint(teacher_bp)
app.register_blueprint(student_bp)

with app.app_context():
    seed()


if __name__ == "__main__":
    app.run(debug=True)
