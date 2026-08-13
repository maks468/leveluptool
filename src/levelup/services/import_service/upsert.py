"""Idempotent upsert of mapped rows into `schools`, keyed on rspo_id.

Re-import must only ever touch RSPO-sourced columns on `schools` -- never
pipeline_state, activity_log, school_contacts, or school_scores. Schools
absent from a newer snapshot are marked is_active=False, never deleted.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from levelup.models.import_batch import ImportBatch
from levelup.models.school import EvidenceSource, School
from levelup.services.import_service.column_mapping import map_row
from levelup.services.import_service.exclusion_rules import classify


def run_import(session: Session, rows: Iterable[dict], batch: ImportBatch) -> ImportBatch:
    existing_by_rspo_id: dict[str, School] = {s.rspo_id: s for s in session.query(School).all()}

    # Mark everything inactive up front; anything upserted below flips back
    # to True. Avoids a giant NOT IN (...) with tens of thousands of ids.
    for school in existing_by_rspo_id.values():
        school.is_active = False

    counts = {
        "total": 0,
        "imported": 0,
        "excluded_other_type": 0,
        "excluded_adult_education": 0,
        "excluded_special_needs": 0,
        "excluded_zero_students": 0,
        "errors": 0,
    }
    error_samples: list[str] = []
    now = datetime.now(timezone.utc)

    for row in rows:
        counts["total"] += 1
        outcome = classify(row)

        if outcome == "exclude_other_type":
            counts["excluded_other_type"] += 1
            continue
        if outcome == "exclude_adult_education":
            counts["excluded_adult_education"] += 1
            continue
        if outcome == "exclude_special_needs":
            counts["excluded_special_needs"] += 1
            continue
        if outcome == "exclude_online_school":
            # "Szkoła w Chmurze" online-network branches (see
            # exclusion_rules.is_online_school). Counted under other_type
            # rather than a new ImportBatch column -- the batch schema
            # stays untouched, and the exclusion is still visible in code
            # and in per-run totals.
            counts["excluded_other_type"] += 1
            continue
        if outcome == "exclude_zero_students":
            counts["excluded_zero_students"] += 1
            continue

        try:
            kwargs = map_row(row)
        except Exception as exc:  # noqa: BLE001 -- one bad row must not abort a 19k-row import
            counts["errors"] += 1
            if len(error_samples) < 20:
                error_samples.append(f"{row.get('RSPO', '?')}: {exc}")
            continue

        rspo_id = kwargs["rspo_id"]
        existing = existing_by_rspo_id.get(rspo_id)
        if existing:
            # A manually-corrected or enrichment-discovered website must
            # survive a re-import -- a stale/blank RSPO field is never
            # allowed to clobber a verified correction.
            if existing.website_url_source in (EvidenceSource.MANUAL, EvidenceSource.ENRICHMENT):
                kwargs = {k: v for k, v in kwargs.items() if k not in ("website_url", "website_url_source")}
            for key, value in kwargs.items():
                setattr(existing, key, value)
            existing.is_active = True
            existing.last_seen_in_import_at = now
            existing.last_import_batch_id = batch.id
        else:
            new_school = School(**kwargs, last_import_batch_id=batch.id, is_active=True)
            session.add(new_school)
            existing_by_rspo_id[rspo_id] = new_school
        counts["imported"] += 1

    batch.row_count_total = counts["total"]
    batch.row_count_imported = counts["imported"]
    batch.row_count_excluded_adult = counts["excluded_adult_education"]
    batch.row_count_excluded_special_needs = counts["excluded_special_needs"]
    batch.row_count_excluded_zero_students = counts["excluded_zero_students"]
    batch.row_count_excluded_other_type = counts["excluded_other_type"]
    batch.row_count_errors = counts["errors"]
    batch.imported_at = now
    batch.status = "done"

    session.flush()
    return batch, error_samples
