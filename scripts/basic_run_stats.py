"""Progress + before/after stats for the full basic-pool re-run.

Reads the snapshot written by the pool-builder (basic_run.json), compares
it to the live DB for every school the job has finished, and reports
cumulative and per-100 outcomes. READ-ONLY.

    python /app/scripts/basic_run_stats.py <job_id>
"""

import json
import sqlite3
import sys

sys.path.insert(0, "/app/scripts")
from sample_rerun import state_of  # noqa: E402

RANK = {"not_enriched": 0, "basic": 1, "partial": 2, "successful": 3}


def main() -> None:
    job_id = int(sys.argv[1])
    conn = sqlite3.connect("file:/app/data/levelup.db?mode=ro", uri=True)
    snap = json.load(open("/app/data/basic_run.json", encoding="utf-8"))
    before = snap["before"]
    order = snap["ordered_ids"]
    scores = snap["scores"]

    # Job item statuses.
    status = dict(
        conn.execute(
            "select school_id, status from enrichment_job_items where job_id=?", (job_id,)
        ).fetchall()
    )
    done = [sid for sid in order if status.get(sid) == "success"]
    failed = [sid for sid in order if status.get(sid) == "failed"]
    pending = sum(1 for sid in order if status.get(sid) in ("pending", "running"))

    gained_teacher = gained_email = swapped = lost = up = via_vision = 0
    band = {"80+": [0, 0], "70-80": [0, 0], "60-70": [0, 0], "50-60": [0, 0], "<50": [0, 0]}

    def band_of(score):
        if score >= 80:
            return "80+"
        if score >= 70:
            return "70-80"
        if score >= 60:
            return "60-70"
        if score >= 50:
            return "50-60"
        return "<50"

    for sid in done:
        b = before[str(sid)]
        a = state_of(conn, sid)
        bk = band_of(scores.get(str(sid), scores.get(sid, 0)))
        band[bk][0] += 1
        got = not b["teacher_name"] and a["teacher_name"]
        if got:
            gained_teacher += 1
            band[bk][1] += 1
        if not b["teacher_email"] and a["teacher_email"]:
            gained_email += 1
        if b["teacher_name"] and a["teacher_name"] and b["teacher_name"] != a["teacher_name"]:
            swapped += 1
        if b["teacher_name"] and not a["teacher_name"]:
            lost += 1
        if RANK[a["level"]] > RANK[b["level"]]:
            up += 1
        # vision-derived teachers
        r = conn.execute(
            "select 1 from school_contacts where school_id=? and contact_type='english_coordinator' "
            "and extraction_method='llm_vision' and person_name is not null",
            (sid,),
        ).fetchone()
        if r and got:
            via_vision += 1

    n = len(done)
    print(f"=== basic re-run, job {job_id} ===")
    print(f"  processed        : {n} / {len(order)}   (failed {len(failed)}, pending {pending})")
    if n:
        pct = lambda k: f"{100 * k / n:.1f}%"
        print(f"  gained a teacher : {gained_teacher}  ({pct(gained_teacher)})")
        print(f"    of those via vision (PDF/image): {via_vision}")
        print(f"  gained teacher's email : {gained_email}  ({pct(gained_email)})")
        print(f"  level moved up   : {up}  ({pct(up)})")
        print(f"  teacher swapped  : {swapped}   lost: {lost}   <-- want ~0")
        print(f"\n  yield by score band (schools processed / teachers gained):")
        for k in ("80+", "70-80", "60-70", "50-60", "<50"):
            proc, gain = band[k]
            if proc:
                print(f"    {k:6}: {gain:4}/{proc:<4}  ({100*gain/proc:.0f}%)")


if __name__ == "__main__":
    main()
