"""Samples N schools where the OLD (regex) enrichment pipeline already ran
and failed to find EITHER a director name or a personal director email,
then re-runs each through the NEW LLM-based pipeline (enrich_school_dry_run
-- exact production logic, every DB mutation rolled back) and reports how
many improved vs. are still stuck vs. show anything unexpected.

"Failed" population, precisely: active schools with at least one completed
enrichment attempt (EnrichmentJobItem.status == "success") where EITHER
School.director_name is NULL, OR every "director" SchoolContact row on
file has email IS NULL.

Each school gets its OWN fresh session with the school queried (and thus
attached) inside that same session, so enrich_school_dry_run's rollback
undoes every mutation -- including School-row fields like director_name/
website_url/specialty/is_active -- not just the SchoolContact inserts.

Usage:
    python scripts/eval_sample.py --n 50 --seed 42
    python scripts/eval_sample.py --n 50 --seed 42 --out sample_results.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from levelup.core.db import SessionLocal
from levelup.models.enrichment import EnrichmentJobItem, SchoolContact
from levelup.models.school import School
from levelup.services.enrichment.jobs import enrich_school_dry_run
from levelup.services.enrichment.llm_extract import UsageLimitError


def failed_population(session) -> list[int]:
    attempted_ids = {
        row[0]
        for row in session.query(EnrichmentJobItem.school_id)
        .filter(EnrichmentJobItem.status == "success")
        .distinct()
        .all()
    }
    active_ids = {row[0] for row in session.query(School.id).filter(School.is_active.is_(True)).all()}
    no_director_ids = {
        row[0]
        for row in session.query(School.id).filter(School.director_name.is_(None), School.is_active.is_(True)).all()
    }
    director_contacts = session.query(SchoolContact).filter(SchoolContact.contact_type == "director").all()
    no_email_ids = {c.school_id for c in director_contacts if not c.email}
    has_email_ids = {c.school_id for c in director_contacts if c.email}
    no_personal_email_ids = no_email_ids - has_email_ids
    return sorted((no_director_ids | no_personal_email_ids) & attempted_ids & active_ids)


def old_state(session, school_id: int) -> dict:
    school = session.query(School).filter_by(id=school_id).one()
    contact = session.query(SchoolContact).filter_by(school_id=school_id, contact_type="director").one_or_none()
    return {
        "name": school.name,
        "city": school.city,
        "old_director": school.director_name,
        "old_director_email": contact.email if contact else None,
        "old_source_url": contact.source_url if contact else None,
    }


def run_one(school_id: int) -> dict:
    session = SessionLocal()
    started = time.monotonic()
    try:
        school = session.query(School).filter_by(id=school_id).one()
        result = enrich_school_dry_run(session, school)
        result["_elapsed"] = round(time.monotonic() - started, 1)
        return result
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default=None, help="optional path to dump full JSON results")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        population = failed_population(session)
        rng = random.Random(args.seed)
        sample_ids = rng.sample(population, min(args.n, len(population)))
        before = {sid: old_state(session, sid) for sid in sample_ids}
    finally:
        session.close()

    print(f"failed population size: {len(population)}")
    print(f"sampled {len(sample_ids)} schools (seed={args.seed})\n")

    rows = []
    for i, sid in enumerate(sample_ids, 1):
        b = before[sid]
        row = {"school_id": sid, **b}
        try:
            result = run_one(sid)
        except UsageLimitError as exc:
            row["error"] = f"USAGE_LIMIT: {exc}"
            rows.append(row)
            print(f"[{i}/{len(sample_ids)}] STOPPED -- usage limit hit: {exc}")
            break
        except Exception as exc:  # noqa: BLE001 -- one school's crash must not sink the sample
            row["error"] = str(exc)
            rows.append(row)
            print(f"[{i}/{len(sample_ids)}] {b['name'][:55]!r} -> ERROR: {exc}")
            continue

        row.update(
            {
                "new_director": result.get("director_name"),
                "new_director_email": result.get("director_email"),
                "new_teacher": result.get("teacher_name"),
                "new_teacher_email": result.get("teacher_email"),
                "director_source": result.get("director_source"),
                "director_confidence": result.get("director_confidence"),
                "llm_calls": result.get("llm_calls", 0),
                "escalations": result.get("escalations", 0),
                "vision_calls": result.get("vision_calls", 0),
                "input_tokens": result.get("llm_input_tokens", 0),
                "output_tokens": result.get("llm_output_tokens", 0),
                "elapsed": result.get("_elapsed"),
            }
        )
        rows.append(row)

        director_fixed = (not b["old_director"]) and bool(row["new_director"])
        email_fixed = (not b["old_director_email"]) and bool(row["new_director_email"])
        director_lost = bool(b["old_director"]) and not row["new_director"]
        tags = []
        if director_fixed:
            tags.append("DIRECTOR FOUND")
        if email_fixed:
            tags.append("EMAIL FOUND")
        if director_lost:
            tags.append("DIRECTOR LOST (regression?)")
        if not tags:
            tags.append("still gap")
        print(
            f"[{i}/{len(sample_ids)}] {b['name'][:55]!r} ({b['city']}) -> {', '.join(tags)}  "
            f"[{row['elapsed']}s, {row['llm_calls']} calls, {row['escalations']} esc]"
        )

    # --- summary ---
    completed = [r for r in rows if "error" not in r]
    director_found = sum(1 for r in completed if not r["old_director"] and r["new_director"])
    director_still_missing = sum(1 for r in completed if not r["old_director"] and not r["new_director"])
    email_found = sum(1 for r in completed if not r["old_director_email"] and r["new_director_email"])
    email_still_missing = sum(1 for r in completed if not r["old_director_email"] and not r["new_director_email"])
    director_lost = sum(1 for r in completed if r["old_director"] and not r["new_director"])
    errors = [r for r in rows if "error" in r]
    total_calls = sum(r.get("llm_calls", 0) for r in completed)
    total_escalations = sum(r.get("escalations", 0) for r in completed)
    total_in_tok = sum(r.get("input_tokens", 0) for r in completed)
    total_out_tok = sum(r.get("output_tokens", 0) for r in completed)
    total_elapsed = sum(r.get("elapsed", 0) for r in completed)

    print(f"\n{'=' * 90}")
    print(f"SUMMARY ({len(completed)} completed of {len(rows)} attempted, sample size {len(sample_ids)})")
    print(f"  director name:  {director_found} newly found, {director_still_missing} still missing, {director_lost} LOST")
    print(f"  director email: {email_found} newly found, {email_still_missing} still missing")
    print(f"  errors: {len(errors)}")
    print(f"  llm_calls total: {total_calls}  escalations: {total_escalations}")
    print(f"  tokens total: {total_in_tok} in / {total_out_tok} out")
    print(f"  wall time total: {round(total_elapsed, 1)}s  avg/school: {round(total_elapsed / max(len(completed), 1), 1)}s")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"\nfull results written to {args.out}")


if __name__ == "__main__":
    main()
