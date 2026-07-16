from __future__ import annotations

from levelup.models.school import School
from levelup.services.scoring.common import (
    score_city_size,
    score_language_orientation,
    score_private_status,
    score_school_size,
)


def score_target_cohort_present(school: School, cfg: dict) -> dict:
    max_points = cfg["max_points"]
    if school.has_grades_7_8 is None:
        return {"points": 0, "max": max_points, "basis": "unknown"}
    return {"points": max_points if school.has_grades_7_8 else 0, "max": max_points, "basis": "verified"}


def score(school: School, rubric: dict, city_tiers: dict) -> tuple[int, dict]:
    criteria = rubric["criteria"]
    breakdown = {
        "language_orientation": score_language_orientation(school, criteria["language_orientation"]),
        "school_size": score_school_size(school, criteria["school_size"]),
        "private_status": score_private_status(school, criteria["private_status"]),
        "target_cohort_present": score_target_cohort_present(school, criteria["target_cohort_present"]),
        "city_size": score_city_size(school, criteria["city_size"], city_tiers),
    }
    total = sum(c["points"] for c in breakdown.values())
    return total, breakdown
