"""Before/after for the top-500 basic audit (jobs 93/94/95). READ-ONLY."""
import json, sqlite3, collections, sys
sys.path.insert(0, "/app/scripts")
from sample_rerun import state_of, level_of
RANK = {"not_enriched": 0, "basic": 1, "partial": 2, "successful": 3, "complete": 4}
conn = sqlite3.connect("file:/app/data/levelup.db?mode=ro", uri=True)
snap = json.load(open("/app/data/basic500.json", encoding="utf-8"))
before, meta = snap["before"], snap["meta"]
JOBS = tuple(int(a) for a in sys.argv[1:]) or (93, 94, 95)
done = [r[0] for r in conn.execute(
    f"select distinct school_id from enrichment_job_items "
    f"where job_id in ({','.join(str(j) for j in JOBS)}) and status='success'")]
n=len(done)
up=down=teacher=temail=site_changed=email_changed=0
tiers=collections.Counter(); moves=collections.Counter()
for sid in done:
    b=before[str(sid)]; a=state_of(conn,sid)
    tiers[a["level"]]+=1
    rb,ra=RANK[b["level"]],RANK[a["level"]]
    if ra>rb: up+=1; moves[f'{b["level"]}->{a["level"]}']+=1
    if ra<rb: down+=1
    if not b["teacher_name"] and a["teacher_name"]: teacher+=1
    if not b["teacher_email"] and a["teacher_email"]: temail+=1
    if (b.get("website_url") or "")!=(a.get("website_url") or ""): site_changed+=1
    if (b.get("general_email") or "")!=(a.get("general_email") or ""): email_changed+=1
print(f"=== top-500 basic audit: {n}/500 re-run (failed/pending excluded) ===")
print(f"  GRADE MOVED UP   : {up} ({100*up/max(n,1):.1f}%)   down: {down}")
for m,k in moves.most_common(): print(f"     {m:22} {k}")
print(f"  teacher gained   : {teacher}   teacher email gained: {temail}")
print(f"  website corrected: {site_changed}   office email changed: {email_changed}")
print(f"  tier distribution now: " + ", ".join(f"{L}={tiers[L]}" for L in ("complete","successful","partial","basic","not_enriched")))
