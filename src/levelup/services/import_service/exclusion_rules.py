"""Import-time inclusion/exclusion checks. No user toggle exists for any
of this -- but every exclusion is counted and sampled so filtering a 55k+
row nationwide file never happens silently. See column_mapping.py for the
verified real column names these rely on.

Adult-education rows are NOT excluded -- they're imported and tagged via
School.is_adult_education (see column_mapping.is_adult_education) so they
remain a browsable, filterable category rather than being dropped.
"""

from __future__ import annotations

from levelup.services.import_service.column_mapping import TARGET_TYPE_MAP


def is_target_type(row: dict) -> bool:
    return row.get("Czy szkoła") == "1" and row.get("Typ podmiotu") in TARGET_TYPE_MAP


def classify(row: dict) -> str:
    """Returns 'import' or 'exclude_other_type'."""
    if not is_target_type(row):
        return "exclude_other_type"
    return "import"
