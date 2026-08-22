"""Before/after stats for the basic-pool re-run, spanning jobs 77 + 78.

The run was launched as job 77 over the whole basic pool, then narrowed:
schools already re-run on post-fix code (proven non-converters, minus the
handful with a new PDF/image roster) were dropped, and the remainder
relaunched as job 78. A school counts as processed once it has a
successful item in EITHER job. Compares the before-snapshot in
basic_run.json to the live DB. READ-ONLY.

    python /app/scripts/basic_run_stats.py
"""

import json
import sqlite3
import sys

sys.path.insert(0, "/app/scripts")
from sample_rerun import state_of  # noqa: E402

RANK = {"not_enriched": 0, "basic": 1, "partial": 2, "successful": 3}
JOBS = (77, 78)


def main() -> None:
    conn = sqlite3.connect("file:/app/data/levelup.db?mode=ro", uri=True)
    snap = json.load(open("/app/data/basic_run.json", encoding="utf-8"))
    before = snap["before"]
    scores = snap["scores"]
    eff = set(json.load(open("/app/data/basic_efficient.json", encoding="utf-8"))["ordered_ids"])

    placeholders = ",".join("?" * len(JOBS))
    done = [
        r[0]
        for r in conn.execute(
            f"select distinct school_id from enrichment_job_items "
            f"where job_id in ({placeholders}) and status='success'",
            JOBS,
        )
        if r[0] in eff
    ]
    remaining = len(eff) - len(done)

    def band_of(score):
        return "80+" if score >= 80 else "70-80" if score >= 70 else "60-70" if score >= 60 \
            else "50-60" if score >= 50 else "<50"

    gained = email = swapped = lost = up = via_vision = 0
    band = {k: [0, 0] for k in ("80+", "70-80", "60-70", "50-60", "<50")}

    for sid in done:
        b = before[str(sid)]
        a = state_of(conn, sid)
        bk = band_of(scores.get(str(sid), 0))
        band[bk][0] += 1
        got = not b["teacher_name"] and a["teacher_name"]
        if got:
            gained += 1
            band[bk][1] += 1
            v = conn.execute(
                "select 1 from school_contacts where school_id=? and contact_type='english_coordinator' "
                "and extraction_method='llm_vision' and person_name is not null",
                (sid,),
            ).fetchone()
            if v:
                via_vision += 1
        if not b["teacher_email"] and a["teacher_email"]:
            email += 1
        if b["teacher_name"] and a["teacher_name"] and b["teacher_name"] != a["teacher_name"]:
            swapped += 1
        if b["teacher_name"] and not a["teacher_name"]:
            lost += 1
        if RANK[a["level"]] > RANK[b["level"]]:
            up += 1

    n = len(done)
    pct = lambda k: f"{100 * k / n:.1f}%" if n else "-"
    print(f"=== basic re-run (jobs 77+78) ===")
    print(f"  processed        : {n} / {len(eff)}   (remaining {remaining})")
    if n:
        print(f"  gained a teacher : {gained}  ({pct(gained)})   [{via_vision} via vision]")
        print(f"  gained teacher's email : {email}  ({pct(email)})")
        print(f"  level moved up   : {up}  ({pct(up)})")
        print(f"  churn: swapped {swapped}, lost {lost}")
        print(f"  yield by score band (gained / processed):")
        for k in ("80+", "70-80", "60-70", "50-60", "<50"):
            proc, gain = band[k]
            if proc:
                print(f"    {k:6}: {gain:4}/{proc:<4}  ({100 * gain / proc:.0f}%)")


if __name__ == "__main__":
    main()
