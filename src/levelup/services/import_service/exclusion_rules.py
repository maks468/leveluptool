"""Import-time inclusion/exclusion checks. No user toggle exists for any
of this -- but every exclusion is counted and sampled so filtering a 55k+
row nationwide file never happens silently. See column_mapping.py for the
verified real column names these rely on.

Target types (as of the 2026-07-24 full reset): podstawowa, liceum,
technikum, branżowa I/II only -- policealna was dropped from
TARGET_TYPE_MAP in column_mapping.py, so it now falls out via
is_target_type() below rather than a separate check here.

Adult-education and special-needs rows ARE excluded -- outreach for an
English-language program targets mainstream youth cohorts, and both
categories were confirmed by the user to never belong in this tool.
Special-needs exclusion uses RSPO's own "Specyfika szkoły" == "specjalna"
field directly (an explicit user choice over the narrower name-based
regex previously used) -- it also catches special-ed units embedded in
otherwise plain-named schools that a name match alone would miss.

Schools with zero or unreported total enrollment ("ucz_ogolem") are also
excluded, per explicit user instruction -- note this also sweeps in
sub-units of a larger complex that report enrollment only at the parent
entity (RSPO doesn't distinguish "confirmed empty" from "reports
elsewhere" in this field).
"""

from __future__ import annotations

from levelup.services.import_service.column_mapping import TARGET_TYPE_MAP, _parse_student_count
from levelup.services.import_service.column_mapping import is_adult_education as _is_adult_education_row

SPECIAL_NEEDS_SPECYFIKA = "specjalna"


def is_target_type(row: dict) -> bool:
    return row.get("Czy szkoła") == "1" and row.get("Typ podmiotu") in TARGET_TYPE_MAP


def is_special_needs_by_rspo_field(row: dict) -> bool:
    return row.get("Specyfika szkoły") == SPECIAL_NEEDS_SPECYFIKA


def has_zero_or_missing_students(row: dict) -> bool:
    count = _parse_student_count(row.get("ucz_ogolem"))
    return count is None or count == 0


def classify(row: dict) -> str:
    """Returns 'import', 'exclude_other_type', 'exclude_adult_education',
    'exclude_special_needs', or 'exclude_zero_students'."""
    if not is_target_type(row):
        return "exclude_other_type"
    if _is_adult_education_row(row):
        return "exclude_adult_education"
    if is_special_needs_by_rspo_field(row):
        return "exclude_special_needs"
    if has_zero_or_missing_students(row):
        return "exclude_zero_students"
    return "import"
