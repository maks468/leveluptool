from __future__ import annotations

from levelup.models.school import School, SchoolLevel
from levelup.services.scoring.common import (
    score_city_size,
    score_language_orientation,
    score_private_status,
    score_school_size,
)


def score_ranking(school: School, cfg: dict, ranking_tier: str | None) -> dict:
    max_points = cfg["max_points"]
    if ranking_tier is None:
        return {"points": 0, "max": max_points, "basis": "unknown"}
    return {"points": cfg["tiers"][ranking_tier], "max": max_points, "basis": "verified"}


def score_level_fit(school: School, cfg: dict) -> dict:
    max_points = cfg["max_points"]
    if school.level == SchoolLevel.LICEUM:
        return {"points": cfg["liceum"], "max": max_points, "basis": "verified"}
    return {"points": cfg["technikum"], "max": max_points, "basis": "verified"}


def score(school: School, rubric: dict, city_tiers: dict, ranking_tier: str | None = None) -> tuple[int, dict]:
    criteria = rubric["criteria"]
    breakdown = {
        "language_orientation": score_language_orientation(school, criteria["language_orientation"]),
        "school_size": score_school_size(school, criteria["school_size"]),
        "ranking": score_ranking(school, criteria["ranking"], ranking_tier),
        "private_status": score_private_status(school, criteria["private_status"]),
        "city_size": score_city_size(school, criteria["city_size"], city_tiers),
        "level_fit": score_level_fit(school, criteria["level_fit"]),
    }
    total = sum(c["points"] for c in breakdown.values())
    return total, breakdown
