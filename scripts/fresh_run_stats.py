"""Live stats for the top-1000 never-attempted enrichment run.

Reads fresh_run.json (ordered ids + scores + level/ownership) and the live
DB, and reports outcomes for every finished item: enrichment level reached,
teacher found (and via vision), plus breakdowns by score band and school
level. READ-ONLY.

    python /app/scripts/fresh_run_stats.py <job_id>
"""
import json, sqlite3, sys, collections
sys.path.insert(0, "/app/scripts")
from sample_rerun import level_of  # noqa: E402

def main():
    job = int(sys.argv[1])
    c = sqlite3.connect("file:/app/data/levelup.db?mode=ro", uri=True)
    run = json.load(open("/app/data/fresh_run.json", encoding="utf-8"))
    order, scores, meta = run["ordered_ids"], run["scores"], run["meta"]

    status = dict(c.execute(
        "select school_id, status from enrichment_job_items where job_id=?", (job,)).fetchall())
    done   = [s for s in order if status.get(s) == "success"]
    failed = [s for s in order if status.get(s) == "failed"]
    pend   = sum(1 for s in order if status.get(s) in ("pending","running"))

    lvl = collections.Counter(); teach=0; mail=0; vis=0
    band = collections.defaultdict(lambda:[0,0])   # [processed, teacher]
    slvl = collections.defaultdict(lambda:[0,0])

    def band_of(sc): return "45-47" if sc>=45 else "43-45"
    for sid in done:
        L = level_of(c, sid); lvl[L]+=1
        t = c.execute("select person_name, email, extraction_method from school_contacts "
                      "where school_id=? and contact_type='english_coordinator' and person_name is not null "
                      "order by id desc limit 1",(sid,)).fetchone()
        sc = scores.get(str(sid), scores.get(sid,0)); m = meta[str(sid)]["level"]
        band[band_of(sc)][0]+=1; slvl[m][0]+=1
        if t:
            teach+=1; band[band_of(sc)][1]+=1; slvl[m][1]+=1
            if t[1]: mail+=1
            if t[2]=="llm_vision": vis+=1

    n=len(done)
    print(f"=== top-1000 never-attempted, job {job} ===")
    print(f"  processed : {n} / {len(order)}   (failed {len(failed)}, pending {pend})")
    if n:
        pct=lambda k:f"{100*k/n:.1f}%"
        print(f"\n  ENRICHMENT LEVEL REACHED:")
        for L in ("complete","successful","partial","basic","not_enriched"):
            print(f"    {L:14}: {lvl[L]:4}  ({pct(lvl[L])})")
        print(f"\n  english teacher found : {teach}  ({pct(teach)})   [{vis} via vision]")
        print(f"  teacher WITH email    : {mail}  ({pct(mail)})")
        print(f"\n  teacher yield by score band:")
        for b in ("45-47","43-45"):
            p,g=band[b]
            if p: print(f"    {b}: {g:3}/{p:<4} ({100*g/p:.0f}%)")
        print(f"  teacher yield by school level:")
        for m in ("PRIMARY","LICEUM","TECHNIKUM"):
            p,g=slvl[m]
            if p: print(f"    {m:10}: {g:3}/{p:<4} ({100*g/p:.0f}%)")

if __name__=="__main__": main()
