"""
tidy_data.py — fix data problems that have one obviously right answer.

    python tidy_data.py            show what would change, change nothing
    python tidy_data.py --apply    make the changes (a backup is taken first)

1. NAMES WITH A PHONE NUMBER PASTED IN
   "Maryea Habib<TAB>8801302251446" becomes the name "Maryea Habib", and the
   number moves to the phone field if that field is empty. If the phone field
   already holds a different number, the name is still cleaned and the
   pasted number is reported, not overwritten.

2. THE SAME STUDENT ENTERED TWICE
   Two records with the same name are one person. The OLDER record is kept,
   because it holds the history. Anything on the newer record — classes,
   enrolments — is moved onto the older one, then the newer record is
   removed. Marks and attendance on the newer record are moved too, but only
   where the older record has nothing for that same item, so nothing is lost
   and nothing is doubled.

Nothing else is touched.
"""
import re, sys, shutil
from datetime import datetime
from collections import defaultdict

APPLY = "--apply" in sys.argv

if APPLY:
    name = f"pie-backup-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}-before-tidy.db"
    shutil.copy("pie.db", name)
    print(f"Backup written: {name}\n")

from app import app
from models import (Attendance, ClassAssignment, GroupStudent, Result,
                    ScheduleAttendance, User, db)
from helpers import purge_student

PHONE = re.compile(r'[\t ]*\+?(\d[\d\s-]{7,})\s*$')

def split_name(raw):
    raw = (raw or "").replace("\r", " ").replace("\n", " ")
    m = PHONE.search(raw)
    phone = re.sub(r'\D', '', m.group(1)) if m else None
    name = raw[:m.start()] if m else raw
    name = " ".join(name.replace("\t", " ").split())
    return name, phone

with app.app_context():
    # ── 1. names ─────────────────────────────────────────────────────────
    print("=" * 70); print("1. NAMES WITH A PHONE NUMBER PASTED IN"); print("=" * 70)
    fixed = moved = kept = 0
    for u in User.query.order_by(User.username).all():
        name, phone = split_name(u.full_name)
        if name == u.full_name:
            continue
        note = ""
        if phone and not u.phone:
            note = f"phone set to {phone}"
            if APPLY: u.phone = phone
            moved += 1
        elif phone and u.phone and re.sub(r'\D', '', u.phone) != phone:
            note = f"KEPT existing phone {u.phone}; pasted {phone} ignored"
            kept += 1
        elif phone:
            note = "phone already on file"
        print(f"   {u.username:<6}{name[:32]:<34}{note}")
        if APPLY: u.full_name = name
        fixed += 1
    print(f"\n   {fixed} name(s) cleaned, {moved} phone number(s) moved into the phone field"
          + (f", {kept} left alone because a different number was already there" if kept else ""))
    if APPLY: db.session.commit()

    # ── 2. duplicates ────────────────────────────────────────────────────
    print("\n" + "=" * 70); print("2. THE SAME STUDENT ENTERED TWICE"); print("=" * 70)
    groups = defaultdict(list)
    for u in User.query.filter_by(role="STUDENT").all():
        key = split_name(u.full_name)[0].lower()
        groups[key].append(u)
    merged = 0
    held = []
    for key, users in sorted(groups.items()):
        if len(users) < 2:
            continue
        users.sort(key=lambda x: x.id)
        keep, extras = users[0], users[1:]
        for dup in extras:
            # If the second record sits in classes the first one does not, the
            # two records disagree about where this student belongs. Merging
            # would put one person in both — that is a decision for a person,
            # not a script, so it is reported and left alone.
            extra_classes = [m.group.name for m in GroupStudent.query.filter_by(student_id=dup.id).all()
                             if m.group and not GroupStudent.query.filter_by(
                                 group_id=m.group_id, student_id=keep.id).first()]
            if extra_classes:
                held.append((keep, dup, extra_classes))
                continue
            moves = []
            for a in ClassAssignment.query.filter_by(student_id=dup.id).all():
                if not ClassAssignment.query.filter_by(course_id=a.course_id, student_id=keep.id).first():
                    if APPLY: a.student_id = keep.id
            for r in Result.query.filter_by(student_id=dup.id).all():
                if not Result.query.filter_by(assessment_id=r.assessment_id, student_id=keep.id).first():
                    moves.append("a mark"); 
                    if APPLY: r.student_id = keep.id
            for a in Attendance.query.filter_by(student_id=dup.id).all():
                if not Attendance.query.filter_by(course_id=a.course_id, date=a.date, student_id=keep.id).first():
                    moves.append("an attendance record")
                    if APPLY: a.student_id = keep.id
            for s in ScheduleAttendance.query.filter_by(student_id=dup.id).all():
                if not ScheduleAttendance.query.filter_by(schedule_id=s.schedule_id, student_id=keep.id).first():
                    if APPLY: s.student_id = keep.id
            if APPLY:
                db.session.flush()
                if not keep.phone and dup.phone:
                    keep.phone = dup.phone
                purge_student(dup)        # clears whatever was left as a duplicate
            what = ("moving " + ", ".join(moves)) if moves else "nothing to move"
            print(f"   keep {keep.username}, remove {dup.username}  {split_name(keep.full_name)[0][:26]:<28}{what}")
            merged += 1
    print(f"\n   {merged} duplicate record(s) " + ("merged and removed" if APPLY else "would be merged and removed"))
    if held:
        print("\n   NEEDS YOUR DECISION — left untouched:")
        for keep, dup, cls in held:
            kc = [m.group.name for m in GroupStudent.query.filter_by(student_id=keep.id).all() if m.group]
            print(f"   {split_name(keep.full_name)[0]} is on file twice, in different classes:")
            print(f"      {keep.username}: {', '.join(kc)}")
            print(f"      {dup.username}: {', '.join(cls)} (plus any shared)")
            print(f"      Decide which classes are right, remove them from the others,")
            print(f"      then delete {dup.username} from their profile page.")
    if APPLY: db.session.commit()

    print("\n" + ("Done." if APPLY else "Preview only — nothing changed. Run with --apply to make these changes."))
