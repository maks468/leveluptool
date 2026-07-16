"""Criterion scorers shared by both rubrics. Each returns a dict:
{"points": int, "max": int, "basis": "verified" | "unknown"}

"unknown" means the underlying field is null -- the school can climb once
enrichment (or a rescore after new evidence) fills it in. "verified" means
we have a real answer, even if that answer earns 0 points (e.g. confirmed
public, or confirmed a branch).
"""

from __future__ import annotations

from levelup.models.school import LanguageOrientation, School

LANGUAGE_TIER_KEY = {
    LanguageOrientation.BILINGUAL: "bilingual",
    LanguageOrientation.ENGLISH_FIRST_PLUS_EXTRA: "english_first_plus_extra_language",
    LanguageOrientation.STANDARD_ENGLISH: "standard_english_only",
}


def score_language_orientation(school: School, cfg: dict) -> dict:
    max_points = cfg["max_points"]
    if school.language_orientation is None:
        return {"points": 0, "max": max_points, "basis": "unknown"}
    tier_key = LANGUAGE_TIER_KEY[school.language_orientation]
    return {"points": cfg["tiers"][tier_key], "max": max_points, "basis": "verified"}


def score_school_size(school: School, cfg: dict) -> dict:
    max_points = cfg["max_points"]
    if school.student_count is None:
        return {"points": 0, "max": max_points, "basis": "unknown"}
    ratio = min(school.student_count / cfg["linear_to_students"], 1.0)
    return {"points": round(ratio * max_points), "max": max_points, "basis": "verified"}


def score_private_status(school: School, cfg: dict) -> dict:
    max_points = cfg["max_points"]
    if school.is_private is None:
        return {"points": 0, "max": max_points, "basis": "unknown"}
    return {"points": max_points if school.is_private else 0, "max": max_points, "basis": "verified"}


def score_city_size(school: School, cfg: dict, city_tiers: dict) -> dict:
    max_points = cfg["max_points"]
    if not school.city:
        return {"points": 0, "max": max_points, "basis": "unknown"}
    tiers = cfg["tiers"]
    if school.city in city_tiers["launch_cities"]:
        return {"points": tiers["launch_city"], "max": max_points, "basis": "verified"}
    if school.city in city_tiers["cities_100k_plus"]:
        return {"points": tiers["other_big_city"], "max": max_points, "basis": "verified"}
    return {"points": tiers["smaller_town"], "max": max_points, "basis": "verified"}
