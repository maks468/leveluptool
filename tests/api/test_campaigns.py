"""Campaign containers and the one-place invariant.

A school lives in exactly ONE place: the Library only, the pipeline, or a
single campaign. Every test here is some angle on that invariant -- move
deletes the pipeline row, pull skips campaign members, return is the only
way back, and the two reset actions treat campaigns oppositely (the full
reset clears them, the narrow pipeline clear must not).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import levelup.models  # noqa: F401 -- registers every table on Base.metadata
from levelup.core.db import Base
from levelup.models.campaign import Campaign, CampaignSchool
from levelup.models.enrichment import SchoolContact
from levelup.models.pipeline import ActivityLog, ActivityType, PipelineStage, PipelineState
from levelup.models.school import School, SchoolLevel
from levelup.models.user import User
from levelup.services.admin.reset import clear_pipeline, reset_pipeline_workflow
from levelup.services.pipeline.campaigns import (
    move_to_campaign,
    return_all_to_pipeline,
    return_to_pipeline,
)
from levelup.services.pipeline.stages import pull_into_pipeline


@pytest.fixture()
def session():
    """Four schools: two in the pipeline (one contacted), one already
    parked in another campaign, one plain Library row."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    db.add(User(id=1, display_name="Owner", email=None))
    for school_id in (1, 2, 3, 4):
        db.add(
            School(
                id=school_id,
                rspo_id=str(school_id),
                name=f"school-{school_id}",
                level=SchoolLevel.PRIMARY,
                raw_import_row={},
            )
        )
        db.add(SchoolContact(school_id=school_id, contact_type="general", email=f"info@sp{school_id}.pl"))

    db.add(PipelineState(school_id=1, owner_id=1, stage=PipelineStage.CONTACTED))
    db.add(PipelineState(school_id=2, owner_id=1, stage=PipelineStage.NOT_CONTACTED))
    other = Campaign(id=99, name="Old batch", owner_id=1)
    db.add(other)
    db.add(CampaignSchool(campaign_id=99, school_id=3, stage_at_move="contacted"))

    db.add(Campaign(id=1, name="September mailing", owner_id=1))
    db.commit()
    yield db
    db.close()


def campaign(session, campaign_id=1) -> Campaign:
    return session.query(Campaign).filter_by(id=campaign_id).one()


def test_move_is_move_not_copy(session):
    result = move_to_campaign(session, campaign(session), [1, 2], actor_id=1)

    assert result == {"moved": 2, "not_in_pipeline": 0, "already_in_campaign": 0}
    # Gone from the pipeline...
    assert session.query(PipelineState).count() == 0
    # ...present in exactly one campaign, stage snapshotted.
    memberships = {m.school_id: m for m in session.query(CampaignSchool).filter_by(campaign_id=1)}
    assert memberships[1].stage_at_move == "contacted"
    assert memberships[2].stage_at_move == "not_contacted"


def test_move_skips_what_is_not_in_the_pipeline(session):
    """School 3 sits in another campaign, school 4 is a plain Library row --
    neither can be moved, both are reported rather than silently dropped."""
    result = move_to_campaign(session, campaign(session), [1, 3, 4, 777], actor_id=1)

    assert result == {"moved": 1, "not_in_pipeline": 2, "already_in_campaign": 1}
    assert session.query(CampaignSchool).filter_by(campaign_id=1).count() == 1
    # School 3 stayed exactly where it was.
    assert session.query(CampaignSchool).filter_by(campaign_id=99, school_id=3).count() == 1


def test_pull_into_pipeline_skips_campaign_members(session):
    """The double-contact guard: a parked school cannot come back via a
    pull, only via the explicit return action."""
    result = pull_into_pipeline(session, [3, 4], owner_id=1, actor_id=1)

    assert result == {"pulled_new": 1, "already_in_pipeline": 0, "already_in_campaign": 1}
    assert session.query(PipelineState).filter_by(school_id=4).count() == 1
    assert session.query(PipelineState).filter_by(school_id=3).count() == 0


def test_return_restores_the_stage_it_left_with(session):
    move_to_campaign(session, campaign(session), [1], actor_id=1)
    membership = session.query(CampaignSchool).filter_by(campaign_id=1, school_id=1).one()

    return_to_pipeline(session, membership, actor_id=1)

    state = session.query(PipelineState).filter_by(school_id=1).one()
    assert state.stage == PipelineStage.CONTACTED  # not reset to not_contacted
    assert session.query(CampaignSchool).filter_by(school_id=1).count() == 0
    assert 'Returned from campaign "September mailing"' == state.pull_criteria


def test_return_all_empties_the_container_but_keeps_it(session):
    """Whole-campaign return: every school back on the working queue at its
    own snapshotted stage; the container survives, empty -- emptying and
    deleting stay two separate acts."""
    move_to_campaign(session, campaign(session), [1, 2], actor_id=1)

    moved = return_all_to_pipeline(session, campaign(session), actor_id=1)

    assert moved == 2
    stages = {s.school_id: s.stage for s in session.query(PipelineState).all()}
    assert stages[1] == PipelineStage.CONTACTED  # each at its OWN stage
    assert stages[2] == PipelineStage.NOT_CONTACTED
    assert session.query(CampaignSchool).filter_by(campaign_id=1).count() == 0
    assert session.query(Campaign).filter_by(id=1).count() == 1  # container kept
    # The other campaign is untouched.
    assert session.query(CampaignSchool).filter_by(campaign_id=99).count() == 1


def test_return_all_on_an_empty_campaign_is_harmless(session):
    assert return_all_to_pipeline(session, campaign(session), actor_id=1) == 0


def test_move_and_return_leave_an_activity_trail(session):
    move_to_campaign(session, campaign(session), [1], actor_id=1)
    membership = session.query(CampaignSchool).filter_by(school_id=1).one()
    return_to_pipeline(session, membership, actor_id=1)

    types = [row.activity_type for row in session.query(ActivityLog).filter_by(school_id=1).all()]
    assert ActivityType.MOVED_TO_CAMPAIGN.value in types
    assert ActivityType.PULLED_INTO_PIPELINE.value in types


def test_clear_pipeline_keeps_campaigns_and_their_move_records(session):
    """A campaign is the record that its schools were already contacted --
    the narrow pipeline clear must never touch it."""
    move_to_campaign(session, campaign(session), [1], actor_id=1)

    clear_pipeline(session)

    assert session.query(Campaign).count() == 2
    assert session.query(CampaignSchool).count() == 2
    moved_records = (
        session.query(ActivityLog)
        .filter(ActivityLog.activity_type == ActivityType.MOVED_TO_CAMPAIGN.value)
        .count()
    )
    assert moved_records == 1


def test_full_reset_clears_campaigns(session):
    move_to_campaign(session, campaign(session), [1], actor_id=1)

    counts = reset_pipeline_workflow(session)

    assert session.query(Campaign).count() == 0
    assert session.query(CampaignSchool).count() == 0
    assert counts["campaigns_removed"] == 2
    assert counts["campaign_schools_removed"] == 2
