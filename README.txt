================================================================================
PIE PATHWAYS — LMS (version 2)
Flask 3 + SQLite + Bootstrap 5, branded to the INTO PIE site, sized for a few
hundred students on a PythonAnywhere free account.
================================================================================

WHAT CHANGED SINCE VERSION 1
----------------------------
- Search and filters on every list: name, ID, phone, email, branch, batch,
  course, active/archived, and an attendance threshold. Pages of 50.
- Student profile page — one screen showing how a student is faring, and a
  downloadable PDF report card.
- CSV exports everywhere: student list, login credentials, attendance grid
  (students x dates), mark sheet (students x assessments).
- Bulk add: paste a list of names, get IDs and passwords for all of them, and
  enrol the whole group into courses in one action.
- Archive (default) and permanent delete (typed confirmation) for people.
- Assignments and practice work: teachers set it, students see it on their
  dashboard with due dates and hand in a link, teachers mark it.
- Batches (intakes) and terms. Attendance percentages default to the current
  term instead of all time.
- Branch and phone number on every person.
- Teacher navigation is course-first: one page per course with tabs.
- Storage meter with automatic upload cut-off, so the free account never fills.
- The schedule feature was dropped.

VERSION 3 ADDS
--------------
- Notices. Admins post general announcements (to students, teachers or everyone,
  optionally targeted at one branch or batch). Teachers post course notices from
  inside their own course. Urgent ones show in red at the top. Set a take-down
  date and they clear themselves.
- Duplicate students are refused at creation and skipped in bulk add, existing
  duplicates are flagged, and two records can be merged into one.

UPGRADING FROM VERSION 2: nothing to do. Notices are a new table, added
automatically on the next reload. Do NOT delete lms.db — your data is kept.

UPGRADING FROM VERSION 1: delete lms.db first. The v1 schema is incompatible
and there is no migration; v1 was test data.


WHAT IS IN THE BOX
------------------
app.py              Configuration, authentication, seeding, error handling
models.py           Database tables
helpers.py          Shared queries, permissions, attendance maths
views_admin.py      Administrator pages
views_teacher.py    Teacher pages
views_student.py    Student pages
exports.py          CSV builders and the PDF report card
wsgi.py             PythonAnywhere entry point
requirements.txt    Dependencies
templates/          Jinja templates, grouped by role
static/css/         Brand stylesheet
static/js/          Select-all, bulk register marking, unsaved-work warning
static/uploads/     Uploaded course materials


BRAND COLOURS
-------------
Navy   #07091C   navigation, headers, footers
Red    #E2001A   primary buttons, active tab, brand accents
Amber  #B45309   warnings (kept distinct from red so red stays a brand colour)
Grey   #DFE2E8   rules and borders
Page   #F7F7F8   background


DEFAULT ACCOUNTS
----------------
Admin      admin      / admin123
Teacher    teacher1   / teacher123
Student    1001       / student123
Student    1002       / student123

Change the admin password immediately, then archive the three demo accounts
once you have finished testing.


RUN IT LOCALLY FIRST
--------------------
    python -m venv venv
    venv\Scripts\activate            (PowerShell on Windows)
    source venv/bin/activate         (macOS / Linux)
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000


DEPLOY ON PYTHONANYWHERE (FREE TIER)
------------------------------------
1. Delete the old lms_project folder and lms.db if you deployed version 1.

2. Upload lms_project.zip through Files, into /home/PIEPathways/

3. In a Bash console:

       cd ~
       unzip lms_project.zip
       cd lms_project

4. Install dependencies (use the same Python version as the web app):

       pip3.10 install --user -r requirements.txt

   reportlab is only needed for the PDF report card. If it will not install,
   the app still runs — the report button falls back to a print-ready page.

5. Web tab → Add a new web app → Manual configuration → same Python version.

6. Set on the Web tab:
       Source code:       /home/PIEPathways/lms_project
       Working directory: /home/PIEPathways/lms_project

7. Open the WSGI configuration file, delete everything, paste:

       import os, sys
       path = '/home/PIEPathways/lms_project'
       if path not in sys.path:
           sys.path.insert(0, path)
       os.environ['LMS_SECRET_KEY'] = 'put-a-long-random-string-here'
       from app import app as application

8. Add a static files mapping:
       URL:       /static/
       Directory: /home/PIEPathways/lms_project/static/

9. Reload, then open https://PIEPathways.pythonanywhere.com

   Upgrading from version 2? Skip the lms.db deletion in step 1 — just unzip
   over the folder and reload. The notices table is created for you.

Almost every first-deploy failure is a Python version mismatch between steps 4
and 5. The error log is linked at the top of the Web tab.


SETUP ORDER FOR A NEW TERM
--------------------------
1. Batches & terms  — create the term (make it current) and the intake batch.
2. Teachers         — add staff; usernames are built from their names.
3. Students         — "Add many", paste the intake list, set branch and batch.
4. Logins CSV       — download and hand out.
5. Courses          — create each course, then open it and enrol the batch
                      in one click, choosing the teacher who runs it.

After that, teachers work entirely from My courses.


STORAGE ON THE FREE TIER
------------------------
- Student submissions are always links (Google Drive, Docs). Nothing is stored.
- Teacher materials may be uploaded, 5 MB per file.
- The Storage page shows usage. Amber past 250 MB; uploads are refused at
  350 MB with a message telling teachers to use links instead.
- Delete old files from the Storage page at the end of each term.

If you need more, the PythonAnywhere $5/month tier gives 1 GB and a custom
domain. Nothing in the code needs to change.


BACKUPS AND MAINTENANCE
-----------------------
- Everything is in lms.db next to app.py. Download it from the Files tab
  weekly, and always before uploading a new version.
- Uploaded materials live in static/uploads/ and are not in lms.db.
- Free accounts must be renewed every three months from the Web tab.
- To update the code: upload the new zip, unzip over the folder, press Reload.
  lms.db is never inside the zip, so your data survives.
- Mark changes are recorded in an audit log table (audit_log) with who and when.
================================================================================
