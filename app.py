"""PIE Scheduler — application factory, authentication, seed."""
import os
from datetime import date

from flask import (Flask, abort, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from sqlalchemy import event
from sqlalchemy.engine import Engine
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)

from helpers import human_size, page_args, read_only_guard, storage_usage
from models import (BRANCHES, COURSES_LIST, CourseMaterial, Term, User, db)

BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("PIE_SECRET_KEY", "pie-scheduler-change-this-2026"),
        SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE_DIR, "pie.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        UPLOAD_FOLDER=UPLOAD_DIR,
        STORAGE_BUDGET=250 * 1024 * 1024,
        STORAGE_HARD_LIMIT=350 * 1024 * 1024,
        ORG_NAME="PIE Scheduler",
    )
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ── context processor ────────────────────────────────────────────────────
    import json as _json

    @app.template_filter("from_json")
    def _from_json(v):
        try:
            return _json.loads(v or "[]")
        except ValueError:
            return []

    @app.context_processor
    def inject_globals():
        return {
            "page_args": page_args,
            "today": date.today(),
            "today_str": date.today().isoformat(),
            "BRANCHES": BRANCHES,
            "COURSES_LIST": COURSES_LIST,
            "human_size": human_size,
            "org_name": app.config["ORG_NAME"],
        }

    # ── auth routes ──────────────────────────────────────────────────────────
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
                if not user.is_active:
                    flash("This account is archived. Contact admin.", "danger")
                    return redirect(url_for("login"))
                login_user(user)
                return redirect(url_for("dashboard"))
            flash("Wrong username or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        if current_user.is_admin:
            return redirect(url_for("admin.overview"))
        if current_user.is_teacher:
            return redirect(url_for("teacher.my_schedule"))
        if current_user.is_viewer:
            return redirect(url_for("viewer.search"))
        return redirect(url_for("student.dashboard"))

    @app.route("/change-password", methods=["POST"])
    @login_required
    def change_password():
        current_pw = request.form.get("current_password", "")
        new_pw     = request.form.get("new_password", "")
        confirm    = request.form.get("confirm_password", "")
        if not current_user.check_password(current_pw):
            flash("Current password is wrong.", "danger")
        elif len(new_pw) < 6:
            flash("New password must be at least 6 characters.", "danger")
        elif new_pw != confirm:
            flash("New passwords do not match.", "danger")
        else:
            current_user.set_password(new_pw)
            current_user.initial_password = None
            db.session.commit()
            flash("Password changed successfully.", "success")
        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/materials/<int:mid>/open")
    @login_required
    def open_material(mid):
        item = db.session.get(CourseMaterial, mid)
        if not item:
            abort(404)
        if item.is_link:
            from flask import redirect as redir
            return redir(item.file_path_or_link)
        return send_from_directory(app.config["UPLOAD_FOLDER"],
                                   item.file_path_or_link, as_attachment=True)

    # ── error handlers ───────────────────────────────────────────────────────
    @app.errorhandler(401)
    def unauth(_):
        return redirect(url_for("login"))

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code="403",
                               message="You don't have permission to view that page."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code="404",
                               message="Nothing lives at that address."), 404

    @app.errorhandler(413)
    def too_large(_):
        flash("That file exceeds the 5 MB limit. Share it as a link instead.", "danger")
        return redirect(request.referrer or url_for("dashboard"))

    # ── blueprints ───────────────────────────────────────────────────────────
    from views_admin   import bp as admin_bp
    from views_teacher import bp as teacher_bp
    from views_student import bp as student_bp
    from views_viewer import bp as viewer_bp

    app.before_request(read_only_guard)

    app.register_blueprint(admin_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(viewer_bp)

    # ── seed ─────────────────────────────────────────────────────────────────
    # ── how SQLite behaves when several people save at once ─────────────
    #
    # By default SQLite locks the whole file for a write and gives up
    # instantly if somebody else holds it, which shows the person a "database
    # is locked" error. Two settings fix that:
    #
    #   WAL        readers carry on while one person writes, instead of
    #              everybody queueing behind a single lock
    #   busy_timeout  a writer waits its turn for up to 15 seconds rather
    #              than failing at once — a save takes milliseconds, so the
    #              queue clears long before anyone notices
    #
    # Together these turn a visible error into a short, invisible wait.
    @event.listens_for(Engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    with app.app_context():
        db.create_all()
        _seed()
        _seed_viewer()

    return app


def _seed_viewer():
    """
    The fixed front-desk account. Created once; never duplicated, and never
    overwritten if the password has since been changed.
    """
    if User.query.filter_by(username="studentviewer").first():
        return
    v = User(
        username="studentviewer",
        full_name="Student Records Viewer",
        role="STUDENT_VIEWER",
        initial_password="pie@viewer2026",
    )
    v.set_password("pie@viewer2026")
    db.session.add(v)
    db.session.commit()


def _seed():
    """Create admin account if database is empty."""
    if User.query.first():
        return
    admin = User(
        username="admin",
        full_name="System Administrator",
        role="ADMIN",
        initial_password="pie@admin2026",
    )
    admin.set_password("pie@admin2026")
    db.session.add(admin)

    # Create a default current term
    today = date.today()
    term = Term(
        name=f"Term 1 {today.year}",
        start_date=today.replace(month=1, day=1),
        end_date=today.replace(month=12, day=31),
        is_current=True,
    )
    db.session.add(term)
    db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
