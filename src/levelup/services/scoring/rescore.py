"""Re-applies the current rubric config to every school's already-stored
evidence. Never reads the CSV -- only `schools` columns + confirmed
ranking matches. Always inserts a new SchoolScore row (even at an
unchanged rubric_version) and repoints CurrentScore.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from levelup.models.ranking import RankingEntry, SchoolRankingMatch
from levelup.models.school import School, SchoolLevel
from levelup.models.score import CurrentScore, RubricType, SchoolScore
from levelup.services.scoring import primary_rubric, secondary_rubric
from levelup.services.scoring.rubric_loader import load_city_tiers, load_rubric


def _tier_from_rank(rank: int) -> str:
    if rank <= 100:
        return "top_100_national"
    if rank <= 300:
        return "top_300_or_strong_regional"
    return "ranked_anywhere"


def _lookup_ranking_tier(session: Session, school_id: int) -> str | None:
    match = (
        session.query(SchoolRankingMatch, RankingEntry)
        .join(RankingEntry, SchoolRankingMatch.ranking_entry_id == RankingEntry.id)
        .filter(SchoolRankingMatch.school_id == school_id, SchoolRankingMatch.match_status == "confirmed")
        .order_by(SchoolRankingMatch.ranking_year.desc())
        .first()
    )
    if match is None:
        return None
    _, entry = match
    return _tier_from_rank(entry.rank)


def _upsert_current_score(session: Session, school_id: int, rubric_type: RubricType, score_id: int) -> None:
    pointer = (
        session.query(CurrentScore)
        .filter_by(school_id=school_id, rubric_type=rubric_type)
        .one_or_none()
    )
    if pointer:
        pointer.score_id = score_id
    else:
        session.add(CurrentScore(school_id=school_id, rubric_type=rubric_type, score_id=score_id))


SECONDARY_LEVELS = (SchoolLevel.LICEUM, SchoolLevel.TECHNIKUM)


def rescore_school(session: Session, school: School, primary_cfg: dict, secondary_cfg: dict, city_tiers: dict) -> bool:
    """Returns False (no score computed) for anything no rubric was ever
    specified for: adult-education programs, and the vocational/policealna
    levels -- never fabricate a rubric that wasn't asked for."""
    if school.is_adult_education:
        return False

    if school.level == SchoolLevel.PRIMARY:
        total, breakdown = primary_rubric.score(school, primary_cfg, city_tiers)
        rubric_type, version = RubricType.PRIMARY, primary_cfg["version"]
    elif school.level in SECONDARY_LEVELS:
        ranking_tier = _lookup_ranking_tier(session, school.id)
        total, breakdown = secondary_rubric.score(school, secondary_cfg, city_tiers, ranking_tier)
        rubric_type, version = RubricType.SECONDARY, secondary_cfg["version"]
    else:
        return False

    score_row = SchoolScore(
        school_id=school.id,
        rubric_type=rubric_type,
        rubric_version=version,
        total_score=total,
        criterion_breakdown=breakdown,
    )
    session.add(score_row)
    session.flush()
    _upsert_current_score(session, school.id, rubric_type, score_row.id)
    return True


def rescore_all(session: Session) -> dict[str, int]:
    primary_cfg = load_rubric("primary")
    secondary_cfg = load_rubric("secondary")
    city_tiers = load_city_tiers()

    counts = {"primary": 0, "secondary": 0, "unscored": 0}
    schools = session.query(School).filter(School.is_active.is_(True)).all()
    for school in schools:
        scored = rescore_school(session, school, primary_cfg, secondary_cfg, city_tiers)
        if not scored:
            counts["unscored"] += 1
        elif school.level == SchoolLevel.PRIMARY:
            counts["primary"] += 1
        else:
            counts["secondary"] += 1
    session.commit()
    return counts


if __name__ == "__main__":
    from levelup.core.db import SessionLocal

    s = SessionLocal()
    try:
        result = rescore_all(s)
        print(
            f"Rescored: {result['primary']} primary, {result['secondary']} secondary "
            f"({result['unscored']} unscored -- vocational/policealna/adult-education)"
        )
    finally:
        s.close()
