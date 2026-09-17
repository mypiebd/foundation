"""
migrate.py — bring an existing pie.db up to this version. Safe to run twice.

    python migrate.py            check and migrate
    python migrate.py --dry-run  report only, change nothing

What it does:
  1. Backs up pie.db with a timestamp before touching anything.
  2. Adds the new columns if they are missing (room, attachments, receipt,
     work_hours) — existing rows keep NULL and stay valid.
  3. Creates the fixed studentviewer account if absent.
  4. Links historical schedule rows to their ClassGroup where the match is
     certain, so student routines can find them. Anything uncertain is
     reported, never guessed.
  5. Reports the old 'batch' table if present. It is no longer used — class
     groups replaced it — but the table and its rows are left alone so an
     older database still opens cleanly.
  6. Runs SQLite's integrity check.

Nothing is deleted. No schedule row has its date, time or teacher changed.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "pie.db")
DRY  = "--dry-run" in sys.argv

NEW_COLUMNS = [
    ("class_schedule", "room",            "VARCHAR(100)"),
    ("class_schedule", "group_id",        "INTEGER"),
    ("class_schedule", "slot_id",         "INTEGER"),
    ("user",           "work_hours",      "VARCHAR(255)"),
    ("user",           "days_off",        "VARCHAR(32)"),
    ("assessment",     "attachment_name", "VARCHAR(255)"),
    ("assessment",     "attachment_key",  "VARCHAR(255)"),
    ("assessment",     "attachment_mime", "VARCHAR(120)"),
    ("assessment",     "attachment_size", "INTEGER"),
    ("result",         "file_name",       "VARCHAR(255)"),
    ("result",         "file_key",        "VARCHAR(255)"),
    ("result",         "file_mime",       "VARCHAR(120)"),
    ("result",         "file_size",       "INTEGER"),
    ("result",         "student_note",    "TEXT"),
    ("result",         "received",        "BOOLEAN DEFAULT 0"),
    ("result",         "received_at",     "DATETIME"),
    ("result",         "received_by",     "INTEGER"),
    ("course",         "mnemonic",        "VARCHAR(40)"),
    ("course",         "awarding_body",   "VARCHAR(120)"),
    ("course",         "level",           "VARCHAR(80)"),
    ("course",         "credits",         "INTEGER"),
    ("course",         "learning_hours",  "INTEGER"),
    ("course",         "assessment",      "TEXT"),
    ("course",         "outcomes",        "TEXT"),
]


def cols(c, table):
    try:
        return {r[1] for r in c.execute(f'PRAGMA table_info("{table}")')}
    except sqlite3.Error:
        return set()


def tables(c):
    return {r[0] for r in
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def main():
    if not os.path.exists(DB):
        print("No pie.db here. Start the app once and it will create one.")
        return

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = os.path.join(BASE, f"pie-backup-{stamp}.db")
    if not DRY:
        shutil.copy2(DB, backup)
        print(f"Backup written: {os.path.basename(backup)}")
    else:
        print("-- dry run, no backup needed --")

    con = sqlite3.connect(DB)
    c = con.cursor()
    have = tables(c)
    print(f"\n{len(have)} tables found")

    # ── 1. columns ──────────────────────────────────────────────────────
    added = skipped = 0
    print("\nCOLUMNS")
    for table, col, decl in NEW_COLUMNS:
        if table not in have:
            print(f"   skip  {table}.{col} — no such table yet")
            continue
        if col in cols(c, table):
            skipped += 1
            continue
        print(f"   add   {table}.{col}  {decl}")
        if not DRY:
            c.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {decl}')
        added += 1
    print(f"   -> {added} added, {skipped} already present")

    # ── 2. the fixed viewer account ─────────────────────────────────────
    print("\nSTUDENT RECORDS VIEWER")
    if "user" in have:
        row = c.execute("SELECT id, role FROM user WHERE username='studentviewer'").fetchone()
        if row:
            print(f"   already exists (id {row[0]}, role {row[1]}) — left alone")
        else:
            print("   will be created on next app start (studentviewer / pie@viewer2026)")

    # ── 3. link historical rows to their class group ────────────────────
    print("\nSCHEDULE LINKS")
    if {"class_schedule", "class_group", "class_slot"} <= have:
        total = c.execute("SELECT COUNT(*) FROM class_schedule").fetchone()[0]
        loose = c.execute(
            "SELECT COUNT(*) FROM class_schedule "
            "WHERE group_id IS NULL AND student_id IS NULL "
            "AND class_type != 'Break'").fetchone()[0]
        print(f"   {total} schedule rows, {loose} with no group and no student")

        rows = c.execute(
            "SELECT id, task, teacher_id, date, start_time, end_time, course_id "
            "FROM class_schedule WHERE group_id IS NULL "
            "AND class_type != 'Break'").fetchall()
        groups = c.execute(
            "SELECT id, name, teacher_id, course_id FROM class_group").fetchall()
        slots = c.execute(
            "SELECT id, group_id, weekday, start_time, end_time FROM class_slot").fetchall()

        matched = ambiguous = unmatched = 0
        report = []
        for sid, task, tid, dt, st, en, cid in rows:
            try:
                wd = datetime.strptime(str(dt)[:10], "%Y-%m-%d").weekday()
            except ValueError:
                unmatched += 1
                continue
            # a match must agree on name, teacher, weekday and both times
            cands = []
            for gid, gname, gtid, gcid in groups:
                if gtid != tid:
                    continue
                if (gname or "").strip().lower() != (task or "").strip().lower():
                    continue
                for slid, sgid, swd, sst, sen in slots:
                    if sgid == gid and swd == wd and str(sst) == str(st) \
                       and str(sen) == str(en):
                        cands.append((gid, slid))
            if len(cands) == 1:
                gid, slid = cands[0]
                if not DRY:
                    c.execute("UPDATE class_schedule SET group_id=?, slot_id=? "
                              "WHERE id=?", (gid, slid, sid))
                matched += 1
            elif len(cands) > 1:
                ambiguous += 1
                if len(report) < 12:
                    report.append(f"   ambiguous  {str(dt)[:10]} {st} {task}")
            else:
                unmatched += 1
                if len(report) < 12:
                    report.append(f"   no match   {str(dt)[:10]} {st} {task}")

        print(f"   linked with confidence : {matched}")
        print(f"   ambiguous, left alone  : {ambiguous}")
        print(f"   no match, left alone   : {unmatched}")
        for r in report:
            print(r)
        if ambiguous or unmatched:
            print("   -> review these under Classes > Data check in the app")

    if not DRY:
        con.commit()

    # ── 3b. the retired batch table ─────────────────────────────────────
    print("\nRETIRED TABLES")
    if "batch" in have:
        n = c.execute("SELECT COUNT(*) FROM batch").fetchone()[0]
        print(f"   'batch' still present with {n} row(s) — no longer used, "
              f"left untouched")
        print("   Intakes are now class groups: Classes > All classes")
    else:
        print("   none")

    # ── 4. integrity ────────────────────────────────────────────────────
    print("\nINTEGRITY")
    print("   " + c.execute("PRAGMA integrity_check").fetchone()[0])
    fk = c.execute("PRAGMA foreign_key_check").fetchall()
    print(f"   foreign key problems: {len(fk)}")
    con.close()

    print("\nDone." if not DRY else "\nDry run complete — nothing changed.")
    if not DRY:
        print(f"If anything looks wrong, restore with:\n"
              f"   copy {os.path.basename(backup)} pie.db")


if __name__ == "__main__":
    main()
