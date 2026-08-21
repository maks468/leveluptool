"""Current English-teacher coverage across the register. READ-ONLY.

Reports the numbers that matter for outreach: how many target schools have
a named English teacher, how many have that teacher's own email, and how
many are stuck at "basic" (director + office email, no teacher).
"""

import sqlite3

c = sqlite3.connect("file:/app/data/levelup.db?mode=ro", uri=True)
q = lambda s: c.execute(s).fetchone()[0]

TARGET = "s.is_active=1 and s.is_adult_education=0 and s.specialty is null"
ATTEMPTED = (
    "exists(select 1 from enrichment_job_items i where i.school_id=s.id and i.status='success')"
)
TEACHER_NAMED = (
    "exists(select 1 from school_contacts x where x.school_id=s.id "
    "and x.contact_type='english_coordinator' and x.person_name is not null and x.person_name != '')"
)
TEACHER_EMAIL = (
    "exists(select 1 from school_contacts x where x.school_id=s.id "
    "and x.contact_type='english_coordinator' and x.email is not null and x.email != '')"
)

print("=== English-teacher coverage among successfully-enriched target schools ===")
tot = q(f"select count(*) from schools s where {TARGET} and {ATTEMPTED}")
named = q(f"select count(*) from schools s where {TARGET} and {ATTEMPTED} and {TEACHER_NAMED}")
mail = q(f"select count(*) from schools s where {TARGET} and {ATTEMPTED} and {TEACHER_EMAIL}")
print(f"  enriched successfully : {tot}")
print(f"  teacher NAMED         : {named}  ({100*named/max(tot,1):.1f}%)")
print(f"  teacher WITH own email: {mail}  ({100*mail/max(tot,1):.1f}%)")
print(f"  no teacher            : {tot - named}")
print()

print("=== vendor / authority addresses still stored (should be 0 new ones) ===")
BAD = ("librus.pl", "vulcan.edu.pl", "cke.gov.pl", "edupage.org")
for v in BAD:
    rows = c.execute(
        "select sc.school_id, sc.contact_type, sc.email from school_contacts sc where sc.email like ?",
        (f"%@%{v}",),
    ).fetchall()
    for r in rows:
        print(f"  school {r[0]} [{r[1]}] {r[2]}")
total_bad = sum(
    c.execute("select count(*) from school_contacts where email like ?", (f"%@%{v}",)).fetchone()[0]
    for v in BAD
)
print(f"  total: {total_bad}")
print("  (these predate the fix; the verifier now rejects them on any future run)")
