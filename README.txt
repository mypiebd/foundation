PIE SCHEDULER
=============
Scheduling, attendance and records for PIE International Education.


UPGRADING AN EXISTING DATABASE
------------------------------
If you already have a pie.db with your students and classes in it, copy it
into this folder and run:

    python migrate.py --dry-run     see what would change
    python migrate.py               do it

It backs up pie.db with a timestamp first, adds the new columns, creates the
records-viewer account, and links historical schedule rows to their class
where the match is certain. Nothing is deleted and no class has its date,
time or teacher changed. Safe to run twice.


SUBJECTS, CLASSES AND DESCRIPTIONS
----------------------------------
There are only two things now:

    SUBJECT  - IELTS, GED Social Studies, IQ Physics. One per thing taught.
    CLASS    - a group of days and times under a subject, with a teacher
               and its students. Batch or one-to-one.

The old "Batches & terms" intake list is gone. It held nothing, did nothing,
and confused the two ideas above. Terms moved to People > Terms, where they
belong - a term is only the window attendance percentages are measured over.

EDITING A SUBJECT
Classes > Subjects > open one > Edit subject. You can change the code, the
name, and write the description. Renaming is safe: attendance, marks and
routines follow the subject itself, not its name. Changing the CODE changes
what prints on every routine and register, so the form warns you.

The description page also holds, all optional: module code, awarding body,
level, credits, learning hours, how it is assessed (one line each) and what
students will learn (one line each).

WHO SEES IT
All three. Admin sees it on the subject page, teachers above their course
tabs, students on their own subject page. Students see the first six topics
with a button to show the rest.

The eighteen subjects already have descriptions written in - the INTO module
specifications for the IQ modules, and the published test formats for IELTS,
GED and SAT. Edit any of them freely.

TAKING A SUBJECT TWO WAYS
A student can be in the batch AND have a one-to-one in the same subject.
Nothing stops it and the clash checker handles it, because it looks at the
student's whole diary. The subject page lists every class under it so you can
see which is which, and a student's routine shows both.


THE REGISTER BELONGS TO A CLASS, NOT A SUBJECT
----------------------------------------------
Two one-to-one students in the same subject sit at different times. They must
never share a register, so the Register tab follows the actual dated class:

  * pick a date with no class and it says so, and draws nothing
  * two classes on the same date and it offers both, so you pick the one
    you taught
  * the roll is only that class's students
  * attendance is written against that session, so each class keeps its own
    record; the course total is updated at the same time for the percentages

WHAT A STUDENT SEES
A student's subject page lists ONLY the classes they are in. One-to-one
classes are usually named after the student, so listing every class under a
subject showed one student another student's name. It no longer does.
Administrators still see every class under the subject.


WHEN CLASSES RUN OUT
--------------------
The dashboard warns you when any running class has 45 days or fewer left on
its timetable. Anything under 15 days is marked urgent. Classes with no end
date never appear - they keep generating.

Each row has an Extend button, and "Extend them together" opens the class
list filtered to just those classes.

BULK EXTEND
Classes > All classes > tick the ones you want > a bar appears at the bottom:

    Add this many classes    e.g. 20 taught classes each
    Remove the end date      they run until you stop them

Every class is clash-checked as it rebuilds, so a bulk extend cannot create a
double booking.


BACKUP
------
People > Download backup.

Everything the centre has is in one file. The button sends you a dated copy,
taken through SQLite so it is consistent even if someone is saving at the
time. Keep it somewhere other than the server.

Do it weekly. Nothing takes one automatically.


ACTIVITY
--------
People > Activity. Who changed what, newest first, filterable by person and
by action. Deletions are marked in red.

Class changes, stops, pauses, deletions, roll changes, room assignments,
subject edits, student deletions, bulk extends and backups are all recorded.

(Until now the log was written but never saved - log_action added the entry
to the session and left it there, so the table stayed empty. Fixed.)


RENAMING A CLASS
----------------
Classes > open one > Class name > Save the timetable.

The name is what students see on their routine, so it is worth getting right.
Renaming relabels every future dated class too; past ones keep the name they
were taught under.

If you change ONLY the name or the venue, the timetable is left completely
alone and saved straight away - no clash screen, because nothing about the
times changed.


CHANGING A CLASS TEACHER
------------------------
Classes > open one > Days and times > change the teacher > Save.

The new teacher is checked against every day first. If any of them will not
fit, NOTHING IS CHANGED - you get a screen headed "That change would leave
gaps", listing the problem days with what would work instead:

  * keep the time and give that day to a teacher who is free
  * move the time on the same day
  * leave that day out
  * use it anyway, where only some dates clash

The existing timetable stays booked until you confirm. Before this check
existed, moving a class to a teacher who was busy deleted every session and
rebuilt none.


WHO A ROUTINE BELONGS TO
------------------------
A student's routine comes from the classes they are actually in:

    Student -> class membership -> the dated class

Course enrolment is deliberately NOT used. Being enrolled in GED Social
Studies means the student studies the subject; it does not mean they sit in
every other student's one-to-one under it. Before this change, one student's
private session could appear on another student's sheet.

The consequence: a student enrolled on a subject but not put into a class has
an empty routine. That is a gap in the data, not something to paper over, so
CLASSES > DATA CHECK lists them. Where the subject has exactly one class the
repair is unambiguous, and one button attaches them all.


DAILY ROUTINE AND ROOMS
-----------------------
Classes > Daily routine & rooms.

    Pick the date -> see that day's classes -> type the room -> Save rooms

Type anything operational: Room 1, Lab, Conference Room. Enter jumps to the
next box. Values are saved against that date only - tomorrow is untouched,
and nothing else about the class changes. Online classes show ONLINE.

Daily PDF prints the day with rooms for the front desk. The same room then
appears on student and teacher routines automatically.


STUDENT RECORDS VIEWER
----------------------
A fourth account type for the front desk, counselling and management.

    studentviewer / pie@viewer2026

Search by name, student ID or phone, then view profile, classes, attendance,
marks, assignment status and routine. It cannot change anything - not by
button, not by typing an edit address, not by a crafted request. Write verbs
are refused before the page is even reached. Submitted files are not
downloadable from this account.


HOW LONG A CLASS RUNS
---------------------
When you set a class up, three choices:

    Until I stop it            no end date; the safe default for a batch
    For a set number of classes   e.g. 20 classes
    Until a set date           a fixed finish

A COUNT MEANS TAUGHT CLASSES. Ask for 20 and you get exactly 20 on the
timetable. Days off, protected breaks and clashes are skipped over, not
counted against the 20, so a package of 20 is really 20 lessons. The form
tells you roughly when it will finish as you type.

Same on an existing class: Classes > open it > Keep it going longer >
"Add this many classes". Or extend to a date, or remove the end date so it
runs until you stop it.


ASSIGNMENTS WITH FILES
----------------------
Teachers attach the paper itself, not only a link. Word, PDF or an image, up
to 15 MB. Script and executable files are refused.

Students open the assignment, download the brief, and upload their work -
file, link, or both, with an optional note.

The hand-in has four states the student can see:

    Not Submitted -> Submitted -> Received -> Marked

SUBMITTED means it reached the system. RECEIVED means the teacher has
confirmed they have it. A teacher cannot enter a mark until they have
confirmed receipt, so a student is never left wondering whether the work
arrived. Sending work again clears the receipt, since it is new work.

Every student on the subject gets the work, whoever teaches their class.
Earlier, a teacher who ran no class on that subject silently created an
assignment that reached nobody. A student added after the work was set gets
their row the moment the submissions page is opened, and if a subject has no
students at all the teacher is told rather than left guessing.

Teachers see everything on Course > Work set > Submissions: who has handed
in, the file to download, a Mark received button, then the mark box.

Files are stored under random names outside the source folder and served
only through a route that checks permission. A student can reach their own
submission and nobody else's.


RUN IT (Windows)
----------------
Open the folder that contains app.py. Click the address bar, type cmd, Enter.

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000   Sign in: admin / pie@admin2026

The system starts empty. You add everything yourself.


THE FIRST HOUR
--------------
The dashboard shows a checklist. In order:

1  TEACHERS. Add each one and set their working days and hours. Tick the days
   they work, set from and to, use "Apply to every ticked day" to fill the rest.
   Nothing can ever be booked outside those hours.

   Protected time: on a teacher's edit screen add blocks such as Friday prayer
   1:00-2:00 PM. Nothing can be booked over them.

2  SUBJECTS. One per subject - IELTS, GED Social Studies, SAT Math. Not one per
   batch. The same subject can be taught as a batch AND one-to-one underneath.

3  STUDENTS. Add one at a time, or paste a whole intake with Add many.
   Download Logins CSV to hand out IDs and passwords.

4  CLASSES. Set up a class: pick the subject, batch or one-to-one, the teacher,
   then add a row for each day with its own time. Saturday 10:00 and Tuesday
   2:00 in the same class is fine. Tick who attends. Leave it running until
   you stop it.


HOW SUBJECTS AND CLASSES FIT TOGETHER
-------------------------------------
    SUBJECT: GED Social Studies
      |
      |-- "GED SS Morning Batch"  Batch    Sumaya   12 students
      |      Sat 12:00-1:30 PM, Tue 4:00-5:30 PM
      |
      |-- "Orin - GED SS"         1-on-1   Sazid     1 student
             Sun 10:00-11:00 AM

One subject. Different ways of teaching it. Registers, marks and lesson notes
all roll up to the subject, so a student doing both sees one record.


WHEN A TIME IS ALREADY TAKEN
----------------------------
Setting up a class never silently drops a day. If any of your times will not
fit, the system stops before creating anything and shows you a screen headed
"Some of those times are taken", with the reason for each one and what else
would work:

  KEEP THE TIME, CHANGE THE TEACHER
    Another teacher is free at exactly that hour. The student's day and time
    do not move, so nobody needs telling. Chosen for you by default.

  KEEP THE DAY, MOVE THE TIME
    The nearest working times on the same day with the same teacher, closest
    first. Never chosen for you, because it needs the student's agreement.

  LEAVE THAT DAY OUT
    The class runs on the other days. Add this one later if something frees up.

  BOOK IT ANYWAY
    Shown when some dates are free and only a few clash. Books the free ones.

Nothing is created until you press "Confirm and create the class".

If you give some days to a different teacher, you get one class record per
teacher - each with the right days - so registers and reports stay correct.


THE BREAK RULE
--------------
After two classes back to back a teacher needs 30 minutes. So 10:00-11:00 and
11:00-12:00 means the next class can start at 12:30, not 12:00.

The system does not just refuse. Ask for 12:00 and it answers:

    Adeeb Ahmed would have 3 classes in a row. Needs a 30-minute break
    first, so the earliest is 12:30 PM.
    [ Use 12:30 PM ]  [ Use 12:45 PM ]  [ Use 1:00 PM ]

One click and the time is set. The same suggestions appear when you change a
single class, and while you are building a new one.

No break is invented where classes are not adjacent. A 10:00 class and a 3:00
class need nothing in between.


MANAGING A CLASS
----------------
Classes > open one:

  DAYS AND TIMES   change a time, add a day, drop one. Future classes are
                   rebuilt on the new pattern and clash-checked as they go.
                   Choose from today onwards, or the whole run.
  STUDENTS         add or remove at any time.
  PAUSE            suspend between two dates. Those classes are cancelled and
                   the slot frees up. Resume puts them back.
  KEEP IT GOING    extend the finish date, or set no end date at all.
  FINISH           cancel everything ahead; past records are kept.
  REMOVE DATES     delete a holiday week without ending the class.
  DELETE           removes the class and every session. Needs DELETE typed.

Build ahead on the Classes page tops every running class up 3, 6 or 12 months.


THE TIMETABLE
-------------
Day, Week or Month - the layout changes with the choice.

DAY gives every teacher's full timeline: classes, protected time, and the gaps
between. Any run of 3 classes with no break is flagged in red. Every free gap
of an hour or more has a "Use this slot" button - click it to book a student
straight in, or to keep the time clear for a break or prayer.

Click any class to move it, change the teacher, cancel it or delete it -
without touching the rest of its run.


WHAT TEACHERS SEE
-----------------
MY SCHEDULE in Day, Week or Month. Day shows their timeline with free gaps.

STILL TO WRITE UP sits at the top: any class that has finished without
attendance or lesson notes, with how long ago it ended and a button straight
to it.

WRITE IT UP is one screen. Mark who came - with All present for the usual case
- and type the topic, how it went and the homework. One save does both. The
course register updates at the same time, so nothing is entered twice.

MY COURSES shows every subject they teach, whether they got there through a
batch, a one-to-one, or direct enrolment.


ROUTINES AS PDF
---------------
Routines in the menu. Choose who - all students, one student, a batch, a
course, all teachers, one teacher, or the whole centre - pick the dates, and
download.

Student routines are a card: name and ID, the weekly pattern, then the dates
grouped by month. Classes only. Days with nothing are left out. Cancelled
classes are hidden from students and shown to admin.

Quick buttons for this week, next week and this month.


BACKUP
------
Everything lives in pie.db. Copy that one file somewhere safe and date it.
Do it weekly, and always before deleting anything permanently.
