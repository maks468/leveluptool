"""Pick a random re-run sample from already-enriched schools and snapshot
their CURRENT state, so a before/after comparison is exact rather than
reconstructed. READ-ONLY.

    python /app/scripts/sample_rerun.py snapshot --partial 100 --basic 400 \
        --seed 822 --out /app/data/rerun_sample.json

    python /app/scripts/sample_rerun.py compare --in /app/data/rerun_sample.json

"snapshot" writes the sample plus each school's level, teacher, and emails.
"compare" re-reads the same schools and reports what moved.
"""

import argparse
import json
import random
import sqlite3
import sys

DB = "file:/app/data/levelup.db?mode=ro"

TARGET = "s.is_active=1 and s.is_adult_education=0 and s.specialty is null"
PRIO_MAIL = (
    "exists(select 1 from school_contacts x where x.school_id=s.id "
    "and x.contact_type in ('director','english_coordinator') "
    "and x.email is not null and x.email != '')"
)
TEACHER_NAMED = (
    "exists(select 1 from school_contacts x where x.school_id=s.id "
    "and x.contact_type='english_coordinator' "
    "and x.person_name is not null and x.person_name != '')"
)
DIRECTOR_NAMED = (
    "exists(select 1 from school_contacts x where x.school_id=s.id "
    "and x.contact_type='director' and x.person_name is not null and x.person_name != '')"
)
GENERAL_MAIL = (
    "exists(select 1 from school_contacts x where x.school_id=s.id "
    "and x.contact_type='general' and x.email is not null and x.email != '')"
)

LEVEL_SQL = {
    "partial": f"not {PRIO_MAIL} and {TEACHER_NAMED}",
    "basic": f"not {PRIO_MAIL} and not {TEACHER_NAMED} and {DIRECTOR_NAMED} and {GENERAL_MAIL}",
}


def level_of(conn, sid):
    """The school's current Library level, computed the same way the UI does."""
    row = conn.execute(
        "select "
        " max(case when contact_type='english_coordinator' "
        "          and email is not null and email != '' then 1 else 0 end),"
        " max(case when contact_type='director' "
        "          and email is not null and email != '' then 1 else 0 end),"
        " max(case when contact_type='english_coordinator' "
        "          and person_name is not null and person_name != '' then 1 else 0 end),"
        " max(case when contact_type='director' "
        "          and person_name is not null and person_name != '' then 1 else 0 end),"
        " max(case when contact_type='general' "
        "          and email is not null and email != '' then 1 else 0 end) "
        "from school_contacts where school_id=?",
        (sid,),
    ).fetchone()
    tmail, dmail, teacher, director, general = [bool(x) for x in (row or (0, 0, 0, 0, 0))]
    if tmail:
        return "complete"
    if dmail:
        return "successful"
    if teacher:
        return "partial"
    if director and general:
        return "basic"
    return "not_enriched"


def state_of(conn, sid):
    teacher = conn.execute(
        "select person_name, email from school_contacts "
        "where school_id=? and contact_type='english_coordinator' "
        "and person_name is not null and person_name != '' order by id desc limit 1",
        (sid,),
    ).fetchone()
    director = conn.execute(
        "select person_name, email from school_contacts "
        "where school_id=? and contact_type='director' "
        "and person_name is not null and person_name != '' order by id desc limit 1",
        (sid,),
    ).fetchone()
    general = conn.execute(
        "select email from school_contacts where school_id=? and contact_type='general' "
        "and email is not null and email != '' order by id desc limit 1",
        (sid,),
    ).fetchone()
    name, city, site = conn.execute(
        "select name, city, website_url from schools where id=?", (sid,)
    ).fetchone()
    return {
        "school_id": sid,
        "name": name,
        "city": city,
        "website_url": site,
        "level": level_of(conn, sid),
        "teacher_name": teacher[0] if teacher else None,
        "teacher_email": teacher[1] if teacher else None,
        "director_name": director[0] if director else None,
        "director_email": director[1] if director else None,
        "general_email": general[0] if general else None,
    }


def do_snapshot(args):
    conn = sqlite3.connect(DB, uri=True)
    chosen = {}
    for level, want in (("partial", args.partial), ("basic", args.basic)):
        rows = conn.execute(
            f"select s.id from schools s where {TARGET} and {LEVEL_SQL[level]} order by s.id"
        ).fetchall()
        ids = [r[0] for r in rows]
        random.seed(args.seed + len(level))
        picked = random.sample(ids, min(want, len(ids)))
        chosen[level] = sorted(picked)
        print(f"{level}: pool {len(ids)}, sampled {len(picked)}")

    snap = {
        "seed": args.seed,
        "sample": chosen,
        "before": {
            str(sid): state_of(conn, sid)
            for group in chosen.values()
            for sid in group
        },
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    all_ids = [sid for group in chosen.values() for sid in group]
    print(f"\nwrote {args.out} ({len(all_ids)} schools)")
    print("IDS=" + ",".join(str(i) for i in all_ids))


def do_compare(args):
    conn = sqlite3.connect(DB, uri=True)
    snap = json.load(open(args.infile, encoding="utf-8"))
    before = snap["before"]

    LEVEL_RANK = {"not_enriched": 0, "basic": 1, "partial": 2, "successful": 3, "complete": 4}
    per_group = {}

    for group, ids in snap["sample"].items():
        rows = []
        for sid in ids:
            b = before[str(sid)]
            a = state_of(conn, sid)
            rows.append((b, a))
        per_group[group] = rows

    for group, rows in per_group.items():
        n = len(rows)
        print("=" * 78)
        print(f"### {group.upper()} -- {n} schools re-run")
        print("=" * 78)

        up = [x for x in rows if LEVEL_RANK[x[1]["level"]] > LEVEL_RANK[x[0]["level"]]]
        down = [x for x in rows if LEVEL_RANK[x[1]["level"]] < LEVEL_RANK[x[0]["level"]]]
        same = n - len(up) - len(down)

        gained_teacher = [x for x in rows if not x[0]["teacher_name"] and x[1]["teacher_name"]]
        lost_teacher = [x for x in rows if x[0]["teacher_name"] and not x[1]["teacher_name"]]
        changed_teacher = [
            x for x in rows
            if x[0]["teacher_name"] and x[1]["teacher_name"]
            and x[0]["teacher_name"] != x[1]["teacher_name"]
        ]
        gained_tmail = [x for x in rows if not x[0]["teacher_email"] and x[1]["teacher_email"]]
        lost_tmail = [x for x in rows if x[0]["teacher_email"] and not x[1]["teacher_email"]]
        gained_gmail = [x for x in rows if not x[0]["general_email"] and x[1]["general_email"]]
        lost_gmail = [x for x in rows if x[0]["general_email"] and not x[1]["general_email"]]

        pct = lambda k: f"{100 * k / max(n, 1):.1f}%"
        print(f"  level moved UP            : {len(up):4}  ({pct(len(up))})")
        print(f"  level moved DOWN          : {len(down):4}  ({pct(len(down))})  <-- regressions")
        print(f"  unchanged                 : {same:4}  ({pct(same)})")
        print()
        print(f"  gained an English teacher : {len(gained_teacher):4}  ({pct(len(gained_teacher))})")
        print(f"  LOST an English teacher   : {len(lost_teacher):4}  ({pct(len(lost_teacher))})")
        print(f"  teacher NAME changed      : {len(changed_teacher):4}")
        print(f"  gained teacher's email    : {len(gained_tmail):4}  ({pct(len(gained_tmail))})")
        print(f"  LOST teacher's email      : {len(lost_tmail):4}")
        print(f"  gained office email       : {len(gained_gmail):4}")
        print(f"  LOST office email         : {len(lost_gmail):4}")
        print()

        for label, bucket, show_email in (
            ("GAINED TEACHER", gained_teacher, True),
            ("LOST TEACHER (check these)", lost_teacher, False),
            ("TEACHER NAME CHANGED (check these)", changed_teacher, False),
            ("LOST OFFICE EMAIL (check these)", lost_gmail, False),
        ):
            if not bucket:
                continue
            print(f"  --- {label} ({len(bucket)}) ---")
            for b, a in bucket[:40]:
                if label.startswith("GAINED TEACHER"):
                    mail = f"  <{a['teacher_email']}>" if a["teacher_email"] else ""
                    print(f"    {a['school_id']:6} {a['teacher_name']}{mail}")
                elif label.startswith("TEACHER NAME"):
                    print(f"    {a['school_id']:6} {b['teacher_name']!r} -> {a['teacher_name']!r}")
                elif label.startswith("LOST TEACHER"):
                    print(f"    {a['school_id']:6} was {b['teacher_name']!r}  ({b['website_url']})")
                else:
                    print(f"    {a['school_id']:6} was {b['general_email']!r}  ({b['website_url']})")
            if len(bucket) > 40:
                print(f"    ... and {len(bucket) - 40} more")
            print()


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--partial", type=int, default=100)
    s.add_argument("--basic", type=int, default=400)
    s.add_argument("--seed", type=int, default=822)
    s.add_argument("--out", default="/app/data/rerun_sample.json")
    s.set_defaults(func=do_snapshot)
    c = sub.add_parser("compare")
    c.add_argument("--in", dest="infile", default="/app/data/rerun_sample.json")
    c.set_defaults(func=do_compare)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
