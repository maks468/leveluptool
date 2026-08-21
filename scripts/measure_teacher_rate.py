"""Dry-run the FULL enrichment pipeline (crawl + LLM + grounding) for a set
of schools and report whether an English teacher WOULD be found -- without
writing anything to the database.

This is the measuring instrument for the teacher-hit-rate work: run it on a
fixed school sample before and after a change and compare the rate.

Usage (inside the container):
    python /app/scripts/measure_teacher_rate.py 8733 15063 ...
    python /app/scripts/measure_teacher_rate.py --sample 25          # random basic-no-teacher
    python /app/scripts/measure_teacher_rate.py --file /app/data/sample_ids.txt

Prints one line per school plus a summary. Timing is reported per school so
any added latency is visible.
"""

import json
import random
import sqlite3
import sys
import time

from levelup.services.enrichment import llm_extract, scraper
from levelup.services.enrichment.jobs import _resolve_email

DB = "file:/app/data/levelup.db?mode=ro"

BASIC_NO_TEACHER = """
  not exists(select 1 from school_contacts x where x.school_id=s.id
             and x.contact_type in ('director','english_coordinator')
             and x.email is not null and x.email != '')
  and not exists(select 1 from school_contacts x where x.school_id=s.id
             and x.contact_type='english_coordinator'
             and x.person_name is not null and x.person_name != '')
  and exists(select 1 from school_contacts x where x.school_id=s.id
             and x.contact_type='director'
             and x.person_name is not null and x.person_name != '')
  and exists(select 1 from school_contacts x where x.school_id=s.id
             and x.contact_type='general'
             and x.email is not null and x.email != '')
"""
TARGET = "s.is_active=1 and s.is_adult_education=0 and s.specialty is null"


def pick_sample(conn, n, seed=4242):
    rows = conn.execute(
        f"select s.id from schools s join current_scores cs on cs.school_id=s.id "
        f"join school_scores sc on sc.id=cs.score_id "
        f"where {TARGET} and {BASIC_NO_TEACHER} and s.website_url is not null "
        f"order by sc.total_score desc limit 400"
    ).fetchall()
    random.seed(seed)
    return [r[0] for r in random.sample(rows, min(n, len(rows)))]


def run_one(conn, sid):
    row = conn.execute("select name, city, website_url from schools where id=?", (sid,)).fetchone()
    if not row:
        return {"school_id": sid, "error": "not found"}
    name, city, site = row
    t0 = time.time()
    out = {"school_id": sid, "name": name[:60], "city": city}

    # Mirror jobs.py exactly, including the injected LLM nav-picker.
    picker = llm_extract.pick_staff_pages if llm_extract.is_llm_usable() else None
    try:
        result = scraper.scrape_school_website(
            name, site, None, staff_page_picker=picker, city=city
        )
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"crawl {type(exc).__name__}: {exc}"
        out["seconds"] = round(time.time() - t0, 1)
        return out
    crawl_seconds = time.time() - t0
    out["regex_teacher"] = result.get("english_teacher_name")
    out["pages_crawled"] = len(result.get("llm_pages") or [])
    out["js_render_used"] = bool(result.get("js_render_used"))

    # Mirror jobs.py._run_llm_extraction's page selection exactly.
    raw = result.get("llm_pages") or []
    candidates = [
        llm_extract.PreparedPage(url=p["url"], text=p["text"], tier=p["tier"], third_party=p["third_party"])
        for p in raw
        if not p["third_party"]
    ]
    candidates = llm_extract.pages_that_could_prove(candidates, ("director", "english_teacher"))
    pages = llm_extract.cap_pages(candidates)
    out["pages_sent"] = len(pages)
    out["chars_sent"] = sum(len(p.text) for p in pages)
    out["all_emails"] = sorted(result.get("all_emails") or [])

    teacher = None
    teacher_email = None
    director = None
    if pages and llm_extract.is_llm_usable():
        try:
            extraction = llm_extract.extract_contacts(pages, name, city, model=llm_extract.HAIKU_MODEL)
            if extraction is None:
                extraction = llm_extract.extract_contacts(pages, name, city, model=llm_extract.HAIKU_MODEL)
            if extraction is not None:
                grounded = llm_extract.ground_extraction(
                    extraction, {p.url: p.text for p in pages}, name, set()
                )
                for rec in grounded.staff:
                    if rec.role == "english_teacher" and rec.confidence in ("high", "medium"):
                        teacher = rec.name
                        # Mirror jobs.py: the LLM's own pairing OR a
                        # structural match against every crawled address.
                        # Reading rec.email alone understates the real rate.
                        teacher_email = _resolve_email(
                            rec, sorted(result.get("all_emails") or []), rec.name
                        )
                        out["teacher_evidence"] = (rec.evidence or "")[:150]
                        out["teacher_source"] = rec.source_url
                    if rec.role == "director" and rec.confidence in ("high", "medium") and not director:
                        director = rec.name
        except llm_extract.UsageLimitError as exc:
            out["error"] = f"usage limit: {exc}"
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"llm {type(exc).__name__}: {exc}"
    elif not pages:
        out["note"] = "no page could prove a writeable role"
    else:
        out["note"] = "LLM not usable in this process"

    out["llm_teacher"] = teacher
    out["llm_teacher_email"] = teacher_email
    out["llm_director"] = director
    out["crawl_seconds"] = round(crawl_seconds, 1)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main():
    args = sys.argv[1:]
    conn = sqlite3.connect(DB, uri=True)
    if args and args[0] == "--sample":
        ids = pick_sample(conn, int(args[1]))
    elif args and args[0] == "--file":
        ids = [int(x) for x in open(args[1]).read().split()]
    else:
        ids = [int(a) for a in args]

    print(f"dry-run over {len(ids)} schools: {ids}\n")
    rows = []
    for sid in ids:
        r = run_one(conn, sid)
        rows.append(r)
        print(
            f"  id={r['school_id']:6} {r.get('seconds', 0):6.1f}s "
            f"pages={r.get('pages_crawled', 0):2}/{r.get('pages_sent', 0):2} "
            f"js={'Y' if r.get('js_render_used') else 'n'} "
            f"TEACHER={str(r.get('llm_teacher')):28.28} email={str(r.get('llm_teacher_email')):26.26} "
            f"{r.get('error') or r.get('note') or ''}"
        )

    got = [r for r in rows if r.get("llm_teacher")]
    got_email = [r for r in rows if r.get("llm_teacher_email")]
    times = [r.get("seconds", 0) for r in rows]
    print("\n=== SUMMARY ===")
    print(f"  schools            : {len(rows)}")
    print(f"  teacher found      : {len(got)}  ({100*len(got)/max(len(rows),1):.0f}%)")
    print(f"  teacher WITH email : {len(got_email)}  ({100*len(got_email)/max(len(rows),1):.0f}%)")
    print(f"  mean seconds/school: {sum(times)/max(len(times),1):.1f}   total {sum(times)/60:.1f} min")
    print(f"  errors             : {sum(1 for r in rows if r.get('error'))}")
    print("\nJSON:")
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
