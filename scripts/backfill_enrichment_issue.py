"""Backfill schools.enrichment_issue from each school's LATEST enrichment
activity, using the same derivation new runs write live. One-off, run once
after the column lands; safe to re-run (pure overwrite from the same
source). Usage: python scripts/backfill_enrichment_issue.py --apply
"""

import json
import sys

from levelup.core.db import SessionLocal
from levelup.models.pipeline import ActivityLog
from levelup.models.school import School
from levelup.services.enrichment.jobs import _derive_enrichment_issue


def main(apply: bool) -> None:
    session = SessionLocal()
    latest: dict[int, ActivityLog] = {}
    for row in (
        session.query(ActivityLog)
        .filter(ActivityLog.activity_type.in_(["enrichment_completed", "ENRICHMENT_COMPLETED"]))
        .order_by(ActivityLog.id)
    ):
        latest[row.school_id] = row  # later rows overwrite -- newest wins
    changed = 0
    counts: dict[str, int] = {}
    for school_id, row in latest.items():
        meta = json.loads(row.metadata_json or "{}")
        school = session.get(School, school_id)
        if school is None:
            continue
        issue = meta.get("enrichment_issue", "ABSENT")
        if issue == "ABSENT":
            teacher_email = bool(meta.get("found_teacher_email"))
            issue = _derive_enrichment_issue(
                sources_checked=meta.get("sources_checked", []),
                llm_pages=[None] * int(meta.get("llm_pages_sent") or 0),
                teacher_name=school.english_teacher_name,
                teacher_email="x@y.pl" if teacher_email else None,
                website_url=school.website_url,
            )
        if school.enrichment_issue != issue:
            school.enrichment_issue = issue
            changed += 1
        counts[issue or "none"] = counts.get(issue or "none", 0) + 1
    print(f"schools with an enrichment history: {len(latest)}  changed: {changed}")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"   {k:28} {v}")
    if apply:
        session.commit()
        print("APPLIED")
    else:
        session.rollback()
        print("dry run -- nothing written (use --apply)")
    session.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
