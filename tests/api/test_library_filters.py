"""The Library's enrichment and pipeline-membership filters.

The enrichment filter exists twice on purpose: `_compute_enrichment_levels`
decides the level of an already-fetched school (that's what the badge in the
results table shows), while `_enrichment_predicate` says the same thing in
SQL so the filter can narrow, count and paginate the whole ~25k-school
register without fetching it. Two statements of one rule drift apart
silently, so `test_sql_predicates_agree_with_python_levels` runs both over
every fixture school and fails if they ever disagree -- change one and this
tells you to change the other.

Contact fixtures below cover the cases that make the two definitions
non-trivial: an office/recruitment/RODO/vendor address attached to a named
person does NOT make a school "successful", because those are exactly the
addresses `email_priority` ranks below personal.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import levelup.models  # noqa: F401 -- registers every table on Base.metadata
from levelup.api.v1.schools import (
    _apply_filters,
    _base_query,
    _compute_enrichment_levels,
    _enrichment_predicate,
)
from levelup.core.db import Base
from levelup.models.campaign import Campaign, CampaignSchool
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import PipelineStage, PipelineState
from levelup.models.school import School, SchoolLevel
from levelup.models.user import User

# name -> the contacts it has. Each tuple is (contact_type, person_name, email).
SCHOOL_FIXTURES: dict[str, list[tuple[str, str | None, str | None]]] = {
    # -- successful: a personal address on a decision-maker ------------------
    "director-personal-email": [("director", "Anna Wojda", "anna.wojda@sp1.pl")],
    "teacher-personal-email": [("english_coordinator", "Jan Kos", "j.kos@sp2.pl")],
    # A personal address outranks everything else present.
    "personal-plus-office": [
        ("director", "Ewa Nowak", "ewa.nowak@sp3.pl"),
        ("general", None, "sekretariat@sp3.pl"),
    ],
    # Both decision-makers have their own address -- used to pin the
    # teacher-above-director priority.
    "both-personal-emails": [
        ("director", "Ewa Lis", "ewa.lis@sp16.pl"),
        ("english_coordinator", "Tomasz Gruca", "tomasz.gruca@sp16.pl"),
        ("general", None, "sekretariat@sp16.pl"),
    ],
    # -- partial: the English teacher is named, no personal address yet ------
    "teacher-named-only": [("english_coordinator", "Maria Lis", None)],
    # A named teacher beats a named director + office mailbox (partial > basic).
    "teacher-named-and-director-basic": [
        ("english_coordinator", "Zofia Bak", None),
        ("director", "Piotr Zych", None),
        ("general", None, "info@sp5.pl"),
    ],
    # -- basic: director named, and some email exists, just not a personal one
    "director-named-plus-office-email": [
        ("director", "Adam Mak", None),
        ("general", None, "sekretariat@sp6.pl"),
    ],
    # -- not enriched, despite having contact rows --------------------------
    # A director with an office address: email_priority ranks "sekretariat"
    # below personal, so this is NOT successful -- and with no general-type
    # row there's no email to make it basic either.
    "director-with-office-email": [("director", "Ola Rak", "sekretariat@sp7.pl")],
    "director-with-recruitment-email": [("director", "Ola Rak", "rekrutacja@sp8.pl")],
    "director-with-rodo-email": [("director", "Ola Rak", "iod@sp9.pl")],
    "director-with-separated-rodo-email": [("director", "Ola Rak", "dane.osobowe@sp10.pl")],
    "director-with-vendor-email": [("director", "Ola Rak", "m.adamaszek@zontekiwspolnicy.pl")],
    "director-with-vendor-subdomain-email": [("director", "Ola Rak", "biuro2@x.coreconsulting.pl")],
    # Director named but nothing else at all -- basic needs an email too.
    "director-named-no-email": [("director", "Ola Rak", None)],
    # An office mailbox and nobody named.
    "office-email-only": [("general", None, "kontakt@sp13.pl")],
    # Enrichment ran and came back with nothing usable.
    "attempted-found-nothing": [("general", None, None)],
    # -- no contact rows at all ---------------------------------------------
    "never-touched": [],
}

# Enrichment ran against these; every other fixture school is "never attempted".
ATTEMPTED = {
    "director-personal-email",
    "teacher-named-only",
    "director-with-office-email",
    "attempted-found-nothing",
    "office-email-only",
}

IN_PIPELINE = {"director-personal-email", "teacher-named-only", "never-touched"}
IN_CAMPAIGN = {"personal-plus-office"}
# The Library is the available pool: assigned schools are not in it.
VISIBLE = set(SCHOOL_FIXTURES) - IN_PIPELINE - IN_CAMPAIGN


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    db.add(User(id=1, display_name="Owner", email=None))
    db.add(Campaign(id=77, name="Parked batch", owner_id=1))
    job = EnrichmentJob(id=1, requested_by=1, status="done")
    db.add(job)

    for index, (name, contacts) in enumerate(SCHOOL_FIXTURES.items(), start=1):
        db.add(
            School(
                id=index,
                rspo_id=str(index),
                name=name,
                level=SchoolLevel.PRIMARY,
                raw_import_row={},
                is_active=True,
            )
        )
        for contact_type, person_name, email in contacts:
            db.add(
                SchoolContact(
                    school_id=index,
                    contact_type=contact_type,
                    person_name=person_name,
                    email=email,
                )
            )
        if name in ATTEMPTED:
            db.add(EnrichmentJobItem(job_id=1, school_id=index, status="success"))
        if name in IN_PIPELINE:
            db.add(PipelineState(school_id=index, owner_id=1, stage=PipelineStage.NOT_CONTACTED))
        if name in IN_CAMPAIGN:
            db.add(CampaignSchool(campaign_id=77, school_id=index, stage_at_move="not_contacted"))

    db.commit()
    yield db
    db.close()


def names_matching(session, **filters) -> set[str]:
    query = _apply_filters(_base_query(session), **filters)
    return {school.name for school in query.all()}


def expected_levels(session) -> dict[str, str]:
    ids = {school.id: school.name for school in session.query(School).all()}
    levels = _compute_enrichment_levels(session, list(ids))
    return {name: levels[school_id] for school_id, name in ids.items()}


def test_python_levels_match_the_documented_fixture_intent(session):
    """Guards the fixtures themselves: if these stop describing what the
    level rules actually do, every other assertion here is measuring the
    wrong thing."""
    levels = expected_levels(session)
    assert levels["director-personal-email"] == "successful"
    assert levels["teacher-personal-email"] == "successful"
    assert levels["personal-plus-office"] == "successful"
    assert levels["both-personal-emails"] == "successful"
    assert levels["teacher-named-only"] == "partial"
    assert levels["teacher-named-and-director-basic"] == "partial"
    assert levels["director-named-plus-office-email"] == "basic"
    assert levels["director-with-office-email"] == "not_enriched"
    assert levels["director-with-vendor-email"] == "not_enriched"
    assert levels["never-touched"] == "not_enriched"


@pytest.mark.parametrize("level", ["successful", "partial", "basic", "not_enriched"])
def test_sql_predicates_agree_with_python_levels(session, level):
    """The anti-drift check -- see this module's docstring."""
    from_python = {name for name, value in expected_levels(session).items() if value == level}
    from_sql = {
        school.name
        for school in session.query(School).filter(_enrichment_predicate(level)).all()
    }
    assert from_sql == from_python


def test_successful_teacher_is_the_teacher_email_subset_of_successful(session):
    """The top-priority refinement: only schools where the ENGLISH TEACHER's
    own address was found -- a director-only success doesn't qualify."""
    teacher_successes = names_matching(session, enrichment="successful_teacher")

    assert teacher_successes == {"teacher-personal-email", "both-personal-emails"}
    assert "director-personal-email" not in teacher_successes
    # A subset of "successful", never something outside it. (Not asserted
    # strict: pool semantics can hide the director-only successes that
    # would otherwise make the containment proper.)
    assert teacher_successes <= names_matching(session, enrichment="successful")


def test_best_email_prefers_the_teacher_over_the_director(session):
    """The standing priority: for an English-language program the English
    teacher's own address always outranks the director's, which outranks
    the office mailbox."""
    from levelup.api.v1.schools import _compute_best_emails
    from levelup.models.school import School

    ids = {school.name: school.id for school in session.query(School).all()}
    best = _compute_best_emails(session, list(ids.values()))

    assert best[ids["both-personal-emails"]] == "tomasz.gruca@sp16.pl"  # teacher, not director
    assert best[ids["director-personal-email"]] == "anna.wojda@sp1.pl"  # director when no teacher email
    assert best[ids["office-email-only"]] == "kontakt@sp13.pl"  # office as last resort


def test_enriched_is_exactly_the_complement_of_not_enriched(session):
    enriched = names_matching(session, enrichment="enriched")
    not_enriched = names_matching(session, enrichment="not_enriched")

    assert enriched | not_enriched == VISIBLE
    assert enriched & not_enriched == set()
    assert enriched == {
        name for name, level in expected_levels(session).items()
        if level != "not_enriched" and name in VISIBLE
    }


def test_attempted_counts_every_run_whatever_it_found(session):
    """"Attempted" is about whether enrichment RAN, not what it produced --
    so it spans every outcome level, including the runs that came back with
    nothing."""
    attempted = names_matching(session, enrichment="attempted")

    assert attempted == ATTEMPTED & VISIBLE
    assert "attempted-found-nothing" in attempted
    # "director-personal-email" was attempted too, but it's in the pipeline
    # -- the Library (available pool) no longer shows it at all.
    assert "director-personal-email" not in attempted


def test_attempted_and_never_attempted_partition_the_library(session):
    attempted = names_matching(session, enrichment="attempted")
    never_attempted = names_matching(session, enrichment="never_attempted")

    assert attempted | never_attempted == VISIBLE
    assert attempted & never_attempted == set()


def test_attempted_is_independent_of_the_outcome_levels(session):
    """Neither "attempted" nor "enriched" contains the other, which is why
    they're separate filter values rather than one axis: a run can come back
    empty, and RSPO-backfilled contacts arrive without any run at all."""
    attempted = names_matching(session, enrichment="attempted")
    enriched = names_matching(session, enrichment="enriched")

    # Ran, found nothing usable: attempted but not enriched.
    assert "attempted-found-nothing" in attempted - enriched
    # Contacts, but no enrichment job -- the RSPO-backfill shape.
    assert "director-named-plus-office-email" in enriched - attempted


def test_unknown_enrichment_value_narrows_nothing(session):
    assert names_matching(session, enrichment="not-a-real-value") == VISIBLE
    assert names_matching(session, enrichment="all") == VISIBLE


def test_library_is_the_available_pool(session):
    """Assigned schools -- pipeline or campaign -- are not in the Library
    at all, and come back the moment their assignment is removed."""
    assert names_matching(session) == VISIBLE
    for name in IN_PIPELINE | IN_CAMPAIGN:
        assert name not in names_matching(session), name

    # The retired pipeline_status parameter is accepted and ignored, so a
    # saved view from before the change can't crash or resurrect anything.
    assert names_matching(session, pipeline_status="in") == VISIBLE

    # Removal replenishes: free one pipeline school and one campaign school.
    ids = {school.name: school.id for school in session.query(School).all()}
    session.query(PipelineState).filter_by(school_id=ids["never-touched"]).delete()
    session.query(CampaignSchool).filter_by(school_id=ids["personal-plus-office"]).delete()
    session.commit()
    replenished = names_matching(session)
    assert "never-touched" in replenished and "personal-plus-office" in replenished


def test_enrichment_filter_composes_with_the_pool_semantics(session):
    """What's left to work on -- unassigned AND no contact data yet -- is
    now just the enrichment filter, since the pool excludes assigned
    schools by construction."""
    assert names_matching(session, enrichment="not_enriched") == {
        name
        for name, level in expected_levels(session).items()
        if level == "not_enriched" and name in VISIBLE
    }


def test_adult_ed_and_special_needs_are_eliminated_outright(session):
    """Not filterable -- gone. An adult-education program or a dedicated
    special-needs institution never appears in any listing, under any
    filter combination, and the old filter parameters are accepted but
    change nothing (so pre-elimination saved views don't crash or, worse,
    resurface them)."""
    school = session.query(School).filter_by(name="director-personal-email").one()
    school.is_adult_education = True
    other = session.query(School).filter_by(name="teacher-named-only").one()
    other.specialty = "Special-needs school"
    session.commit()

    assert "director-personal-email" not in names_matching(session)
    assert "teacher-named-only" not in names_matching(session)
    # The deprecated parameters are ignored -- they cannot bring them back.
    assert "director-personal-email" not in names_matching(session, include_adult_education=True)
    assert "teacher-named-only" not in names_matching(session, special_needs="only")
    assert "teacher-named-only" not in names_matching(session, special_needs="all")


def test_inactive_schools_stay_excluded(session):
    """Every Library filter runs on top of is_active -- a school dropped from
    a newer RSPO export must not reappear just because it has contacts."""
    session.query(School).filter_by(name="director-personal-email").one().is_active = False
    session.commit()

    assert "director-personal-email" not in names_matching(session, enrichment="successful")
    assert "director-personal-email" not in names_matching(session, pipeline_status="in")
