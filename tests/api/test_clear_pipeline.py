"""Clearing the pipeline without losing enrichment.

The full reset (reset_pipeline_workflow) throws away every contact
enrichment ever found. clear_pipeline is the narrow alternative, and its
whole value is in what it leaves behind -- so most of these tests assert
survival, not deletion. If a future change makes the clear touch contacts,
enrichment jobs, or the names on School, that is the bug this file exists
to catch.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import levelup.models  # noqa: F401 -- registers every table on Base.metadata
from levelup.core.db import Base
from levelup.models.crm import SavedView, SchoolTag, Tag
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityLog, ActivityType, PipelineStage, PipelineState
from levelup.models.school import School, SchoolLevel
from levelup.models.user import User
from levelup.services.admin.reset import clear_pipeline, reset_pipeline_workflow


@pytest.fixture()
def session():
    """Two schools: one pursued and enriched, one only enriched. Both carry
    the full mix of activity so the outreach/record split is exercised."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    db.add(User(id=1, display_name="Owner", email=None))
    db.add(EnrichmentJob(id=1, requested_by=1, status="done"))
    for school_id, name in ((1, "pursued-and-enriched"), (2, "enriched-only")):
        db.add(
            School(
                id=school_id,
                rspo_id=str(school_id),
                name=name,
                level=SchoolLevel.PRIMARY,
                raw_import_row={},
                director_name="Anna Wojda",
                english_teacher_name="Jan Kos",
            )
        )
        db.add(
            SchoolContact(
                school_id=school_id,
                contact_type="director",
                person_name="Anna Wojda",
                email="anna.wojda@sp.pl",
            )
        )
        db.add(EnrichmentJobItem(job_id=1, school_id=school_id, status="success"))
        # Record-of-the-school activity -- must survive.
        db.add(ActivityLog(school_id=school_id, activity_type=ActivityType.ENRICHMENT_COMPLETED.value))
        db.add(ActivityLog(school_id=school_id, activity_type=ActivityType.WEBSITE_URL_CORRECTED.value))

    # Only school 1 was ever pursued.
    db.add(PipelineState(school_id=1, owner_id=1, stage=PipelineStage.CONTACTED, next_action_note="call back"))
    for activity_type in (
        ActivityType.PULLED_INTO_PIPELINE.value,
        ActivityType.STAGE_CHANGED.value,
        ActivityType.NOTE.value,
    ):
        db.add(ActivityLog(school_id=1, activity_type=activity_type))

    db.add(Tag(id=1, name="priority", color="red"))
    db.add(SchoolTag(school_id=1, tag_id=1))
    db.add(SavedView(id=1, owner_id=1, name="High scorers", scope="library", filters_json={}))

    db.commit()
    yield db
    db.close()


def activity_types(session) -> list[str]:
    return sorted(row.activity_type for row in session.query(ActivityLog).all())


def test_enrichment_survives_untouched(session):
    """The reason this action exists. Contacts and enrichment jobs cost
    crawling and LLM calls; rebuilding a pipeline must never spend them."""
    before = session.query(SchoolContact).count()
    result = clear_pipeline(session)

    assert session.query(SchoolContact).count() == before == 2
    assert session.query(EnrichmentJobItem).count() == 2
    assert session.query(EnrichmentJob).count() == 1
    assert result["school_contacts_kept"] == 2
    # The names on School are enrichment output too -- the full reset wipes
    # them, this one must not.
    assert [s.director_name for s in session.query(School).all()] == ["Anna Wojda", "Anna Wojda"]
    assert [s.english_teacher_name for s in session.query(School).all()] == ["Jan Kos", "Jan Kos"]


def test_pipeline_membership_and_follow_ups_are_gone(session):
    clear_pipeline(session)

    assert session.query(PipelineState).count() == 0
    # Stage and follow-up live on that same row, so they go with it.
    assert session.query(School).count() == 2


def test_outreach_activity_goes_and_record_activity_stays(session):
    result = clear_pipeline(session)

    assert activity_types(session) == [
        ActivityType.ENRICHMENT_COMPLETED.value,
        ActivityType.ENRICHMENT_COMPLETED.value,
        ActivityType.WEBSITE_URL_CORRECTED.value,
        ActivityType.WEBSITE_URL_CORRECTED.value,
    ]
    assert result["activity_log_removed"] == 3  # pulled_into_pipeline, stage_changed, note
    assert result["activity_log_kept"] == 4


def test_tags_and_saved_views_are_kept(session):
    """Unlike the full reset -- they describe the Library, not the pursuit."""
    clear_pipeline(session)

    assert session.query(Tag).count() == 1
    assert session.query(SchoolTag).count() == 1
    assert session.query(SavedView).count() == 1


def test_clearing_twice_is_harmless(session):
    clear_pipeline(session)
    second = clear_pipeline(session)

    assert second["pipeline_schools_removed"] == 0
    assert second["activity_log_removed"] == 0
    assert second["school_contacts_kept"] == 2


def test_full_reset_still_destroys_everything(session):
    """Guards the distinction itself: if the two ever converge, one of them
    is broken."""
    reset_pipeline_workflow(session)

    assert session.query(SchoolContact).count() == 0
    assert session.query(EnrichmentJob).count() == 0
    assert session.query(ActivityLog).count() == 0
    assert session.query(Tag).count() == 0
    assert [s.director_name for s in session.query(School).all()] == [None, None]
