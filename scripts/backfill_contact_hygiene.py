"""Canonicalise names and addresses already in the database.

Enrichment canonicalises what it WRITES (jobs._clean_person_name, lowercase
addresses, the deliverability check), but a row is only rewritten when its
person is re-found. Twelve teachers whose names decline wrongly are no
longer discoverable on their schools' sites -- their rows carry job ids 2,
5, 15, 20, 28... while the same schools' director and office rows are
current -- so no amount of re-crawling reaches them. They need fixing in
place.

Dry run by default; pass --apply to write. Writes through the app's own
session and models, never raw SQL against the file.

    python /app/scripts/backfill_contact_hygiene.py
    python /app/scripts/backfill_contact_hygiene.py --apply
"""

from __future__ import annotations

import argparse

from levelup.core.db import SessionLocal
from levelup.models.enrichment import SchoolContact
from levelup.models.school import School
from levelup.services.enrichment.jobs import _clean_person_name
from levelup.services.enrichment.verifier import is_deliverable_shape


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        name_fixes: list[tuple[int, str, str, str]] = []
        email_lower: list[tuple[int, str, str, str]] = []
        email_cleared: list[tuple[int, str, str]] = []

        for row in session.query(SchoolContact).all():
            if row.person_name:
                canonical = _clean_person_name(row.person_name)
                if canonical and canonical != row.person_name:
                    name_fixes.append((row.school_id, row.contact_type, row.person_name, canonical))
                    if args.apply:
                        row.person_name = canonical
            if row.email:
                if not is_deliverable_shape(row.email):
                    # Nothing can be sent here, and the correct address
                    # cannot be inferred -- a blank beats a wrong one.
                    email_cleared.append((row.school_id, row.contact_type, row.email))
                    if args.apply:
                        row.email = None
                        # quality is derived from name+email; recompute it.
                        from levelup.services.enrichment.verifier import classify_contact_quality

                        row.contact_quality = classify_contact_quality(row.person_name, None)
                elif row.email != row.email.lower():
                    email_lower.append((row.school_id, row.contact_type, row.email, row.email.lower()))
                    if args.apply:
                        row.email = row.email.lower()

        # The denormalised copies on `schools` must not drift from the
        # contact rows they mirror.
        school_fixes: list[tuple[int, str, str, str]] = []
        for school in (
            session.query(School)
            .filter((School.director_name.isnot(None)) | (School.english_teacher_name.isnot(None)))
            .all()
        ):
            for field in ("director_name", "english_teacher_name"):
                current = getattr(school, field)
                if not current:
                    continue
                canonical = _clean_person_name(current)
                if canonical and canonical != current:
                    school_fixes.append((school.id, field, current, canonical))
                    if args.apply:
                        setattr(school, field, canonical)

        print(f"=== names to canonicalise: {len(name_fixes)} contact rows ===")
        for sid, ctype, old, new in name_fixes:
            print(f"  {sid:6} [{ctype:19}] {old!r} -> {new!r}")

        print(f"\n=== schools.* name columns: {len(school_fixes)} ===")
        for sid, field, old, new in school_fixes:
            print(f"  {sid:6} [{field:20}] {old!r} -> {new!r}")

        print(f"\n=== addresses to lowercase: {len(email_lower)} ===")
        for sid, ctype, old, new in email_lower:
            print(f"  {sid:6} [{ctype:19}] {old} -> {new}")

        print(f"\n=== undeliverable addresses to clear: {len(email_cleared)} ===")
        for sid, ctype, old in email_cleared:
            print(f"  {sid:6} [{ctype:19}] {old}")

        total = len(name_fixes) + len(school_fixes) + len(email_lower) + len(email_cleared)
        if args.apply:
            session.commit()
            print(f"\nAPPLIED {total} changes.")
        else:
            print(f"\nDRY RUN -- {total} changes would be made. Re-run with --apply.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
