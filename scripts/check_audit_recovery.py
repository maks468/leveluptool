"""Did the re-run recover teachers on the audited schools? READ-ONLY.

All 28 audited "findable" schools were at basic enrichment with NO English
teacher before the fixes, so any english_coordinator row with a name is a
recovery. The 19 audited TRUE NEGATIVES are checked too, in the opposite
direction: a teacher appearing for one of those is a hallucination alarm,
not a win.
"""

import sqlite3

FINDABLE = [
    1038, 1138, 2023, 6379, 6438, 6657, 7990, 8467, 8476, 8681, 8733, 8750, 8848, 8850,
    8866, 8982, 8985, 9008, 9094, 9128, 10884, 12289, 12951, 15063, 15754, 17340, 18047, 18118,
]
TRUE_NEG = [785, 920, 1068, 2086, 3191, 6514, 7383, 7989, 8011, 8785, 8809, 8853, 8857, 8861,
            8960, 9096, 9110, 9177, 17295]

c = sqlite3.connect("file:/app/data/levelup.db?mode=ro", uri=True)


def teacher_of(sid):
    return c.execute(
        "select person_name, email, confidence, extraction_method, source_url, substr(evidence,1,110) "
        "from school_contacts where school_id=? and contact_type='english_coordinator' "
        "and person_name is not null order by id desc limit 1",
        (sid,),
    ).fetchone()


def last_item(sid):
    return c.execute(
        "select i.job_id, i.status from enrichment_job_items i where i.school_id=? "
        "order by i.id desc limit 1",
        (sid,),
    ).fetchone()


print("=== AUDITED AS FINDABLE (28) -- did the re-run recover them? ===")
got = 0
got_email = 0
for sid in FINDABLE:
    t = teacher_of(sid)
    job, status = last_item(sid) or (None, None)
    if t:
        got += 1
        if t[1]:
            got_email += 1
        print(f"  {sid:6} RECOVERED  {t[0][:30]:30} email={str(t[1]):28.28} {t[3]} conf={t[2]}")
        print(f"         src={t[4]}")
    else:
        print(f"  {sid:6} still none (last job {job}, item {status})")
print(f"\n  recovered {got}/{len(FINDABLE)} teachers, {got_email} with a personal email")

print("\n=== AUDITED AS TRUE NEGATIVES (19) -- must stay empty ===")
alarms = []
for sid in TRUE_NEG:
    t = teacher_of(sid)
    if t:
        alarms.append((sid, t))
        print(f"  {sid:6} ALARM: {t[0]} | {t[3]} conf={t[2]}")
        print(f"         evidence: {t[5]}")
if not alarms:
    print("  none -- no teacher invented for any school the audit proved publishes none")
print(f"\n  hallucination alarms: {len(alarms)}/{len(TRUE_NEG)}")
