from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, exists, false, func, not_, or_
from sqlalchemy.orm import Session

from levelup.api.v1.schemas import (
    CityFacetOut,
    SchoolContactOut,
    SchoolListOut,
    SchoolOut,
    VoivodeshipFacetOut,
    WebsiteUrlUpdate,
)
from levelup.core.db import get_session
from levelup.core.security import get_current_user
from levelup.models.campaign import Campaign, CampaignSchool
from levelup.models.enrichment import EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityLog, ActivityType, PipelineState
from levelup.models.school import EvidenceSource, School
from levelup.models.score import CurrentScore, SchoolScore
from levelup.models.user import User
from levelup.services.enrichment.verifier import (
    DATA_PROTECTION_LOCAL_PARTS,
    GENERIC_OFFICE_LOCAL_PARTS,
    LAST_RESORT_LOCAL_PARTS,
    THIRD_PARTY_VENDOR_DOMAINS,
    email_priority,
)

_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

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
    enrichment: str = "all",
    pipeline_status: str = "all",
):
    query = query.filter(School.is_active.is_(True))

    # What contact data enrichment has actually produced for a school --
    # "enriched"/"not_enriched" for the plain split, the three individual
    # levels for narrowing further, "never_attempted" for schools enrichment
    # has never been run against at all. See _enrichment_predicate.
    enrichment_predicate = _enrichment_predicate(enrichment)
    if enrichment_predicate is not None:
        query = query.filter(enrichment_predicate)

    # Pipeline membership. "out" is the one that makes the Library a working
    # queue -- it hides everything already pulled, so what's left is what
    # hasn't been worked yet (the same thing the voivodeship/city facet
    # counts have always meant).
    if pipeline_status == "in":
        query = query.filter(exists().where(PipelineState.school_id == School.id))
    elif pipeline_status == "out":
        query = query.filter(not_(exists().where(PipelineState.school_id == School.id)))

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


# --- The same enrichment levels, as SQL -------------------------------------
#
# _compute_enrichment_levels above is the readable definition, but it runs in
# Python over already-fetched contact rows: fine for the 50 rows of one page,
# useless as a Library filter, which has to narrow, count and paginate across
# the whole ~25k-school register before any rows are fetched. The predicates
# below express the identical rules as correlated EXISTS subqueries so the
# database can do it.
#
# Two definitions of one concept is a drift risk, so it's pinned down by a
# test: tests/api/test_library_filters.py runs both over every school in the
# database and fails if any school is labelled differently. Change one, and
# the suite tells you to change the other.

_EMAIL_SEPARATORS = (".", "_", "+", "-")


def _sql_is_priority_email(col):
    """Mirrors `email_priority(email) == 0` -- an address that is not a known
    shared office mailbox, not recruitment-only, not a RODO/data-protection
    channel, and not an outsourced vendor's.

    The local-part prefix tests run against the whole address instead of
    slicing the local part out first: every pattern is a local-part prefix
    and none contains "@", so "the local part starts with p" and "the address
    starts with p" are the same test -- and for a pattern longer than the
    local part, the "@" is what stops the match, exactly as the Python side's
    startswith() does. No pattern contains a LIKE wildcard, so none needs
    escaping."""
    lowered = func.lower(col)
    separatorless = lowered
    for char in _EMAIL_SEPARATORS:
        separatorless = func.replace(separatorless, char, "")

    disqualifying = [separatorless.like(f"{p}%") for p in DATA_PROTECTION_LOCAL_PARTS]
    for vendor in THIRD_PARTY_VENDOR_DOMAINS:
        disqualifying.append(lowered.like(f"%@{vendor}"))
        disqualifying.append(lowered.like(f"%.{vendor}"))
    disqualifying += [lowered.like(f"{p}%") for p in LAST_RESORT_LOCAL_PARTS]
    disqualifying += [lowered.like(f"{p}%") for p in GENERIC_OFFICE_LOCAL_PARTS]

    return and_(col.isnot(None), col != "", not_(or_(*disqualifying)))


def _contact_exists(*conditions):
    return exists().where(and_(SchoolContact.school_id == School.id, *conditions))


def _enrichment_predicate(enrichment: str):
    """SQL condition for one Library enrichment filter value, or None for
    "all" (and for anything unrecognized, which is treated the same way --
    an unknown value narrows nothing rather than silently emptying the
    Library)."""
    named = and_(SchoolContact.person_name.isnot(None), SchoolContact.person_name != "")

    has_priority_email = _contact_exists(
        SchoolContact.contact_type.in_(("director", "english_coordinator")),
        _sql_is_priority_email(SchoolContact.email),
    )
    teacher_named = _contact_exists(SchoolContact.contact_type == "english_coordinator", named)
    director_named = _contact_exists(SchoolContact.contact_type == "director", named)
    general_email = _contact_exists(
        SchoolContact.contact_type == "general",
        SchoolContact.email.isnot(None),
        SchoolContact.email != "",
    )

    # successful | partial | basic collapses to this: partial and basic each
    # re-test the higher levels only to stay mutually exclusive, which a
    # union doesn't need.
    any_level = or_(has_priority_email, teacher_named, and_(director_named, general_email))

    # An enrichment job item is written for every school a run covers,
    # whatever it finds -- so its mere existence is the record that the
    # school was tried, independent of the outcome.
    attempted = exists().where(EnrichmentJobItem.school_id == School.id)

    return {
        "successful": has_priority_email,
        "partial": and_(not_(has_priority_email), teacher_named),
        "basic": and_(
            not_(has_priority_email), not_(teacher_named), director_named, general_email
        ),
        "enriched": any_level,
        "not_enriched": not_(any_level),
        # A different question from the levels above: those ask what
        # enrichment FOUND, these ask whether it ever RAN. Neither implies
        # the other -- a run that came back empty is attempted but not
        # enriched, and a school carrying RSPO-backfilled director contacts
        # (see cli/backfill_rspo_directors.py) is enriched without ever
        # having been attempted.
        "attempted": attempted,
        "never_attempted": not_(attempted),
    }.get(enrichment)


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
    campaign_name = (
        session.query(Campaign.name)
        .join(CampaignSchool, CampaignSchool.campaign_id == Campaign.id)
        .filter(CampaignSchool.school_id == school.id)
        .scalar()
    )
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
            "website_url_source": school.website_url_source.value if school.website_url_source else None,
            "language_orientation": school.language_orientation.value if school.language_orientation else None,
            "school_profile": school.school_profile,
            "director_name": school.director_name,
            "english_teacher_name": school.english_teacher_name,
            "specialty": school.specialty,
            "name_disambiguator": school.name_disambiguator,
            "enrichment_level": enrichment_level,
            "is_active": school.is_active,
            "in_pipeline": pipeline_state is not None,
            "campaign_name": campaign_name,
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
    enrichment: str = Query("all", description="all|enriched|not_enriched|successful|partial|basic|attempted|never_attempted"),
    pipeline_status: str = Query("all", description="all|in|out -- whether the school is already in the pipeline"),
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
        enrichment=enrichment,
        pipeline_status=pipeline_status,
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
    enrichment: str = Query("all", description="all|enriched|not_enriched|successful|partial|basic|attempted|never_attempted"),
    pipeline_status: str = Query("all", description="all|in|out -- whether the school is already in the pipeline"),
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
        enrichment=enrichment,
        pipeline_status=pipeline_status,
    )
    return {"count": query.count()}


@router.get("/ids")
def list_school_ids(
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
    enrichment: str = Query("all", description="all|enriched|not_enriched|successful|partial|basic|attempted|never_attempted"),
    pipeline_status: str = Query("all", description="all|in|out -- whether the school is already in the pipeline"),
):
    """Every school id matching the given filters, across every page --
    lets the Library's "select all N matching my filters" checkbox act on
    the whole filtered set (e.g. hand-picking 200 schools spread over 4
    pages) rather than only whatever's on the current page."""
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
        enrichment=enrichment,
        pipeline_status=pipeline_status,
    )
    return {"ids": [row[0] for row in query.all()]}


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
    enrichment: str = Query("all", description="all|enriched|not_enriched|successful|partial|basic|attempted|never_attempted"),
    pipeline_status: str = Query("all", description="all|in|out -- whether the school is already in the pipeline"),
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
        enrichment=enrichment,
        pipeline_status=pipeline_status,
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


@router.patch("/{school_id}/website", response_model=SchoolOut)
def update_school_website(
    school_id: int,
    body: WebsiteUrlUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Manual override for when the scraper can't find or reach a school's
    site on its own. Marked EvidenceSource.MANUAL so it outranks RSPO's
    raw field on every future re-import (see upsert.py) -- a correction
    made here is never silently reset. Doesn't run enrichment itself;
    the frontend follows up with a normal POST /enrichment-jobs call for
    this school so the new URL gets tried right away."""
    school = session.query(School).filter_by(id=school_id).one_or_none()
    if school is None:
        raise HTTPException(404, "School not found")

    url = body.website_url.strip()
    if not url:
        raise HTTPException(400, "website_url must not be empty")
    if not _URL_SCHEME_RE.match(url):
        url = f"http://{url}"

    previous_url = school.website_url
    school.website_url = url
    school.website_url_source = EvidenceSource.MANUAL
    session.add(
        ActivityLog(
            school_id=school.id,
            actor_id=user.id,
            activity_type=ActivityType.WEBSITE_URL_CORRECTED.value,
            note=f"Website manually set to {url}" + (f" (was {previous_url})" if previous_url else ""),
            metadata_json={"from": previous_url, "to": url},
        )
    )
    session.commit()

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
