from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import and_, false, func, or_
from sqlalchemy.orm import Session

from levelup.api.v1.schemas import CityFacetOut, SchoolContactOut, SchoolListOut, SchoolOut, VoivodeshipFacetOut
from levelup.core.db import get_session
from levelup.models.enrichment import SchoolContact
from levelup.models.pipeline import PipelineState
from levelup.models.school import School
from levelup.models.score import CurrentScore, SchoolScore
from levelup.services.enrichment.verifier import email_priority

router = APIRouter(prefix="/schools", tags=["schools"])

SCHOOL_TYPE_LEVELS = {
    "primary": ["primary"],
    "secondary": ["liceum", "technikum"],
    "liceum": ["liceum"],
    "technikum": ["technikum"],
    "vocational": ["branzowa_i", "branzowa_ii", "policealna"],
}

SORTABLE_FIELDS = {
    "score": SchoolScore.total_score,
    "name": School.name,
    "students": School.student_count,
}


def _apply_filters(
    query,
    *,
    voivodeship: str | None = None,
    city: str | None = None,
    school_type: str | None = None,
    ownership_public: bool = True,
    ownership_private: bool = True,
    ownership_subtype: str | None = None,
    ownership_include_unverified: bool = True,
    students_min: int | None = None,
    students_max: int | None = None,
    students_include_unknown: bool = True,
    score_min: int | None = None,
    score_max: int | None = None,
    score_include_unscored: bool = True,
    include_adult_education: bool = True,
    special_needs: str = "all",
):
    query = query.filter(School.is_active.is_(True))

    # Dedicated special-needs institutions carry a non-null `specialty`
    # (set from the official name -- see scraper._detect_specialties).
    # "only" narrows to them; "exclude" hides them (the default for ordinary
    # English-program outreach); "all" (default) applies no filter.
    if special_needs == "only":
        query = query.filter(School.specialty.isnot(None))
    elif special_needs == "exclude":
        query = query.filter(School.specialty.is_(None))

    if voivodeship:
        query = query.filter(School.voivodeship == voivodeship)
    if city:
        query = query.filter(School.city == city)
    if school_type and school_type != "all":
        levels = SCHOOL_TYPE_LEVELS.get(school_type, [])
        query = query.filter(School.level.in_(levels))
    if not include_adult_education:
        query = query.filter(School.is_adult_education.is_(False))

    # Public and private are independently toggleable -- both on (the
    # default) means no ownership restriction at all, so even a school
    # with genuinely unknown ownership (is_private IS NULL) stays visible;
    # both off means show nothing, matching the literal "you excluded every
    # category" reading rather than silently falling back to "show
    # everything". ownership_subtype is checked via "is not None" (not
    # truthiness) so an explicitly-empty subtype selection ("no subtypes
    # checked") narrows private results down to none, instead of being
    # indistinguishable from "no subtype filter requested at all".
    if ownership_public and ownership_private:
        if ownership_subtype is not None:
            subtypes = [s for s in ownership_subtype.split(",") if s]
            subtype_conditions = [School.ownership_subtype.in_(subtypes)]
            if ownership_include_unverified:
                subtype_conditions.append(School.ownership_subtype.is_(None))
            # Every non-confirmed-private row (False or NULL) passes through
            # untouched; only rows confirmed private must match the subtype.
            query = query.filter(or_(School.is_private.isnot(True), or_(*subtype_conditions)))
        # else: no restriction at all -- don't filter on is_private.
    elif ownership_public:
        query = query.filter(School.is_private.is_(False))
    elif ownership_private:
        query = query.filter(School.is_private.is_(True))
        if ownership_subtype is not None:
            subtypes = [s for s in ownership_subtype.split(",") if s]
            subtype_conditions = [School.ownership_subtype.in_(subtypes)]
            if ownership_include_unverified:
                subtype_conditions.append(School.ownership_subtype.is_(None))
            query = query.filter(or_(*subtype_conditions))
    else:
        query = query.filter(false())

    if students_min is not None or students_max is not None:
        range_conditions = [School.student_count.isnot(None)]
        if students_min is not None:
            range_conditions.append(School.student_count >= students_min)
        if students_max is not None:
            range_conditions.append(School.student_count <= students_max)
        conditions = [and_(*range_conditions)]
        if students_include_unknown:
            conditions.append(School.student_count.is_(None))
        query = query.filter(or_(*conditions))

    if score_min is not None or score_max is not None:
        range_conditions = [SchoolScore.total_score.isnot(None)]
        if score_min is not None:
            range_conditions.append(SchoolScore.total_score >= score_min)
        if score_max is not None:
            range_conditions.append(SchoolScore.total_score <= score_max)
        conditions = [and_(*range_conditions)]
        if score_include_unscored:
            conditions.append(SchoolScore.total_score.is_(None))
        query = query.filter(or_(*conditions))

    return query


def _base_query(session: Session):
    return session.query(School).outerjoin(
        CurrentScore, CurrentScore.school_id == School.id
    ).outerjoin(SchoolScore, SchoolScore.id == CurrentScore.score_id)


def _compute_enrichment_levels(session: Session, school_ids: list[int]) -> dict[int, str]:
    """School-level enrichment summary, computed from all its contacts
    (director, English teacher, and the nameless "general" mailbox)
    together -- a different, coarser axis than a single contact's own
    failed/partial/verified quality:
    - "successful": a priority (personal, structurally-verified) email
      was found for the director OR the English teacher -- reaches a
      real person directly. A director/teacher contact's own `email`
      field is only ever populated with such a verified address in the
      first place (see jobs.py), so any email present there already
      qualifies -- nothing generic ever gets attached to a name.
    - "partial": no priority email yet, but the English teacher's own
      name is known -- for an English-language program, knowing WHO
      teaches English is itself a useful lead even without their email.
    - "basic": no priority email, no English teacher name, but the
      director's name is known AND the school has SOME email on file
      (even just the shared "general" office mailbox, not tied to the
      director specifically).
    - "not_enriched": nothing usable found yet.
    """
    if not school_ids:
        return {}
    contacts = session.query(SchoolContact).filter(SchoolContact.school_id.in_(school_ids)).all()
    by_school: dict[int, list[SchoolContact]] = {}
    for c in contacts:
        by_school.setdefault(c.school_id, []).append(c)

    def has_priority_email(c: SchoolContact) -> bool:
        return bool(c.email) and email_priority(c.email) == 0

    levels: dict[int, str] = {}
    for school_id in school_ids:
        school_contacts = by_school.get(school_id, [])
        directors = [c for c in school_contacts if c.contact_type == "director"]
        teachers = [c for c in school_contacts if c.contact_type == "english_coordinator"]
        general = [c for c in school_contacts if c.contact_type == "general"]

        if any(has_priority_email(c) for c in directors + teachers):
            levels[school_id] = "successful"
        elif any(c.person_name for c in teachers):
            levels[school_id] = "partial"
        elif any(c.person_name for c in directors) and any(g.email for g in general):
            levels[school_id] = "basic"
        else:
            levels[school_id] = "not_enriched"
    return levels


def _compute_best_emails(session: Session, school_ids: list[int]) -> dict[int, str | None]:
    """The single best contact email per school for an outreach campaign:
    a decision-maker's OWN (personal-verified) address first -- director,
    then English teacher -- otherwise the general office/secretariat mailbox.
    None when no email was found at all. director/english_coordinator
    contacts only ever carry a personal-verified address (see jobs.py), so
    preferring them targets a real person; the general row is the reliable
    fallback that always lands in the school's inbox."""
    if not school_ids:
        return {}
    contacts = session.query(SchoolContact).filter(SchoolContact.school_id.in_(school_ids)).all()
    by_school: dict[int, list[SchoolContact]] = {}
    for c in contacts:
        by_school.setdefault(c.school_id, []).append(c)

    best: dict[int, str | None] = {}
    for school_id in school_ids:
        school_contacts = by_school.get(school_id, [])
        chosen = None
        for contact_type in ("director", "english_coordinator", "general"):
            chosen = next((c.email for c in school_contacts if c.contact_type == contact_type and c.email), None)
            if chosen:
                break
        best[school_id] = chosen
    return best


def _to_out(
    session: Session, school: School, score: SchoolScore | None, enrichment_level: str | None = None
) -> SchoolOut:
    pipeline_state = session.query(PipelineState).filter_by(school_id=school.id).one_or_none()
    if enrichment_level is None:
        enrichment_level = _compute_enrichment_levels(session, [school.id]).get(school.id, "not_enriched")
    return SchoolOut(
        **{
            "id": school.id,
            "rspo_id": school.rspo_id,
            "name": school.name,
            "level": school.level.value,
            "voivodeship": school.voivodeship,
            "city": school.city,
            "is_private": school.is_private,
            "ownership_subtype": school.ownership_subtype.value if school.ownership_subtype else None,
            "ownership_subtype_verified": school.ownership_subtype_verified,
            "student_count": school.student_count,
            "is_adult_education": school.is_adult_education,
            "is_branch": school.is_branch,
            "has_grades_7_8": school.has_grades_7_8,
            "website_url": school.website_url,
            "language_orientation": school.language_orientation.value if school.language_orientation else None,
            "school_profile": school.school_profile,
            "director_name": school.director_name,
            "english_teacher_name": school.english_teacher_name,
            "specialty": school.specialty,
            "name_disambiguator": school.name_disambiguator,
            "enrichment_level": enrichment_level,
            "is_active": school.is_active,
            "in_pipeline": pipeline_state is not None,
            "stage": pipeline_state.stage.value if pipeline_state else None,
            "next_action_note": pipeline_state.next_action_note if pipeline_state else None,
            "next_action_date": pipeline_state.next_action_date if pipeline_state else None,
            "score": None
            if score is None
            else {
                "rubric_type": score.rubric_type.value,
                "rubric_version": score.rubric_version,
                "total_score": score.total_score,
                "criterion_breakdown": score.criterion_breakdown,
                "computed_at": score.computed_at,
            },
        }
    )


@router.get("", response_model=SchoolListOut)
def list_schools(
    session: Session = Depends(get_session),
    voivodeship: str | None = None,
    city: str | None = None,
    school_type: str | None = None,
    ownership_public: bool = True,
    ownership_private: bool = True,
    ownership_subtype: str | None = None,
    ownership_include_unverified: bool = True,
    students_min: int | None = None,
    students_max: int | None = None,
    students_include_unknown: bool = True,
    score_min: int | None = None,
    score_max: int | None = None,
    score_include_unscored: bool = True,
    include_adult_education: bool = True,
    special_needs: str = "all",
    sort: str = "score:desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    result_limit: int | None = Query(None, ge=1, description="Cap the whole result set to the top N by the current sort, e.g. 'top 30 schools'"),
):
    query = _apply_filters(
        _base_query(session),
        voivodeship=voivodeship,
        city=city,
        school_type=school_type,
        ownership_public=ownership_public,
        ownership_private=ownership_private,
        ownership_subtype=ownership_subtype,
        ownership_include_unverified=ownership_include_unverified,
        students_min=students_min,
        students_max=students_max,
        students_include_unknown=students_include_unknown,
        score_min=score_min,
        score_max=score_max,
        score_include_unscored=score_include_unscored,
        include_adult_education=include_adult_education,
        special_needs=special_needs,
    )

    total = query.count()
    if result_limit is not None:
        total = min(total, result_limit)

    field_name, _, direction = sort.partition(":")
    sort_col = SORTABLE_FIELDS.get(field_name, SchoolScore.total_score)
    sort_col = sort_col.desc().nulls_last() if direction != "asc" else sort_col.asc().nulls_last()
    query = query.order_by(sort_col)

    offset = (page - 1) * page_size
    if result_limit is not None:
        effective_limit = max(0, min(page_size, result_limit - offset))
    else:
        effective_limit = page_size

    rows = query.offset(offset).limit(effective_limit).all() if effective_limit > 0 else []
    enrichment_levels = _compute_enrichment_levels(session, [school.id for school in rows])
    items = []
    for school in rows:
        score = (
            session.query(SchoolScore)
            .join(CurrentScore, CurrentScore.score_id == SchoolScore.id)
            .filter(CurrentScore.school_id == school.id)
            .one_or_none()
        )
        items.append(_to_out(session, school, score, enrichment_levels.get(school.id)))

    return SchoolListOut(total=total, page=page, page_size=page_size, items=items)


@router.get("/count")
def count_schools(
    session: Session = Depends(get_session),
    voivodeship: str | None = None,
    city: str | None = None,
    school_type: str | None = None,
    ownership_public: bool = True,
    ownership_private: bool = True,
    ownership_subtype: str | None = None,
    ownership_include_unverified: bool = True,
    students_min: int | None = None,
    students_max: int | None = None,
    students_include_unknown: bool = True,
    score_min: int | None = None,
    score_max: int | None = None,
    score_include_unscored: bool = True,
    include_adult_education: bool = True,
    special_needs: str = "all",
):
    query = _apply_filters(
        _base_query(session).with_entities(School.id),
        voivodeship=voivodeship,
        city=city,
        school_type=school_type,
        ownership_public=ownership_public,
        ownership_private=ownership_private,
        ownership_subtype=ownership_subtype,
        ownership_include_unverified=ownership_include_unverified,
        students_min=students_min,
        students_max=students_max,
        students_include_unknown=students_include_unknown,
        score_min=score_min,
        score_max=score_max,
        score_include_unscored=score_include_unscored,
        include_adult_education=include_adult_education,
        special_needs=special_needs,
    )
    return {"count": query.count()}


@router.get("/export")
def export_schools_csv(
    session: Session = Depends(get_session),
    voivodeship: str | None = None,
    city: str | None = None,
    school_type: str | None = None,
    ownership_public: bool = True,
    ownership_private: bool = True,
    ownership_subtype: str | None = None,
    ownership_include_unverified: bool = True,
    students_min: int | None = None,
    students_max: int | None = None,
    students_include_unknown: bool = True,
    score_min: int | None = None,
    score_max: int | None = None,
    score_include_unscored: bool = True,
    include_adult_education: bool = True,
    special_needs: str = "all",
    sort: str = "score:desc",
):
    """CSV export of a filtered Library segment -- for handing a batch to a
    future teammate or an email tool, matching exactly what's on screen
    (same filters, same sort) rather than a separate ad-hoc query."""
    query = _apply_filters(
        _base_query(session),
        voivodeship=voivodeship,
        city=city,
        school_type=school_type,
        ownership_public=ownership_public,
        ownership_private=ownership_private,
        ownership_subtype=ownership_subtype,
        ownership_include_unverified=ownership_include_unverified,
        students_min=students_min,
        students_max=students_max,
        students_include_unknown=students_include_unknown,
        score_min=score_min,
        score_max=score_max,
        score_include_unscored=score_include_unscored,
        include_adult_education=include_adult_education,
        special_needs=special_needs,
    )
    field_name, _, direction = sort.partition(":")
    sort_col = SORTABLE_FIELDS.get(field_name, SchoolScore.total_score)
    sort_col = sort_col.desc().nulls_last() if direction != "asc" else sort_col.asc().nulls_last()
    query = query.order_by(sort_col)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "rspo_id", "name", "level", "voivodeship", "city", "is_private", "ownership_subtype",
            "student_count", "website_url", "director_name", "english_teacher_name", "score",
            "in_pipeline", "stage",
        ]
    )
    for school in query.all():
        pipeline_state = session.query(PipelineState).filter_by(school_id=school.id).one_or_none()
        score = (
            session.query(SchoolScore)
            .join(CurrentScore, CurrentScore.score_id == SchoolScore.id)
            .filter(CurrentScore.school_id == school.id)
            .one_or_none()
        )
        writer.writerow(
            [
                school.rspo_id,
                school.name,
                school.level.value,
                school.voivodeship or "",
                school.city or "",
                school.is_private if school.is_private is not None else "",
                school.ownership_subtype.value if school.ownership_subtype else "",
                school.student_count if school.student_count is not None else "",
                school.website_url or "",
                school.director_name or "",
                school.english_teacher_name or "",
                score.total_score if score else "",
                "yes" if pipeline_state else "no",
                pipeline_state.stage.value if pipeline_state else "",
            ]
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=schools_export.csv"},
    )


def _scope_to_facet_query(query, scope: str):
    """"library" (default) counts only schools NOT yet pulled into the
    pipeline -- the actually-remaining working set, so a city/voivodeship
    that's been fully worked through drops toward 0 instead of forever
    showing its original nationwide count. "pipeline" is the mirror image:
    counts only schools that ARE in the pipeline, for the Pipeline page's
    own filters."""
    if scope == "pipeline":
        return query.join(PipelineState, PipelineState.school_id == School.id)
    return query.outerjoin(PipelineState, PipelineState.school_id == School.id).filter(
        PipelineState.school_id.is_(None)
    )


@router.get("/facets/voivodeships", response_model=list[VoivodeshipFacetOut])
def list_voivodeships(session: Session = Depends(get_session), scope: str = "library"):
    query = session.query(School.voivodeship, func.count(School.id)).filter(
        School.is_active.is_(True), School.voivodeship.isnot(None)
    )
    query = _scope_to_facet_query(query, scope)
    rows = query.group_by(School.voivodeship).order_by(School.voivodeship).all()
    return [{"voivodeship": v, "count": count} for v, count in rows]


@router.get("/facets/cities", response_model=list[CityFacetOut])
def list_cities(session: Session = Depends(get_session), voivodeship: str | None = None, scope: str = "library"):
    query = session.query(School.city, func.count(School.id)).filter(
        School.is_active.is_(True), School.city.isnot(None)
    )
    if voivodeship:
        query = query.filter(School.voivodeship == voivodeship)
    query = _scope_to_facet_query(query, scope)
    rows = query.group_by(School.city).order_by(func.count(School.id).desc(), School.city).all()
    return [{"city": city, "count": count} for city, count in rows]


@router.get("/{school_id}", response_model=SchoolOut)
def get_school(school_id: int, session: Session = Depends(get_session)):
    school = session.query(School).filter_by(id=school_id).one()
    score = (
        session.query(SchoolScore)
        .join(CurrentScore, CurrentScore.score_id == SchoolScore.id)
        .filter(CurrentScore.school_id == school.id)
        .one_or_none()
    )
    return _to_out(session, school, score)


def _dedupe_contacts(contacts: list[SchoolContact]) -> list[SchoolContact]:
    """Collapses repeat rows for the same (contact_type, person_name) --
    a school enriched multiple times before contacts were upserted in
    place (rather than always inserted fresh) can have several rows for
    the exact same director. Groups by type+name and keeps the single
    best row per group: the best email tier, then most recently
    captured -- a genuinely different person in the same role (e.g. two
    distinct English teachers) has a different name and so isn't
    collapsed at all."""
    groups: dict[tuple[str, str | None], list[SchoolContact]] = {}
    for c in contacts:
        key = (c.contact_type, c.person_name.strip().lower() if c.person_name else None)
        groups.setdefault(key, []).append(c)

    def rank(c: SchoolContact) -> tuple[int, float]:
        tier = email_priority(c.email) if c.email else 3
        return (tier, -c.captured_at.timestamp())

    return [min(group, key=rank) for group in groups.values()]


@router.get("/{school_id}/contacts", response_model=list[SchoolContactOut])
def list_school_contacts(school_id: int, session: Session = Depends(get_session)):
    contacts = (
        session.query(SchoolContact)
        .filter_by(school_id=school_id)
        .order_by(SchoolContact.captured_at.desc())
        .all()
    )
    deduped = _dedupe_contacts(contacts)
    deduped.sort(key=lambda c: c.captured_at, reverse=True)
    return deduped
