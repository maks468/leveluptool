"""The Directory: the full register with each school's assignment -- the
read-only complement to the Library-as-available-pool. Nothing ever
disappears from here; it just changes status."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import levelup.models  # noqa: F401 -- registers every table on Base.metadata
from levelup.api.v1.schools import directory
from levelup.core.db import Base
from levelup.models.campaign import Campaign, CampaignSchool
from levelup.models.pipeline import PipelineStage, PipelineState
from levelup.models.school import School, SchoolLevel
from levelup.models.user import User


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    db.add(User(id=1, display_name="Owner", email=None))
    db.add(Campaign(id=1, name="September wave", owner_id=1))
    for school_id, name, city in (
        (1, "SP AVAILABLE", "Radom"), (2, "SP PURSUED", "Radom"), (3, "SP PARKED", "Opole"),
    ):
        db.add(School(id=school_id, rspo_id=str(school_id), name=name, city=city,
                      level=SchoolLevel.PRIMARY, raw_import_row={}))
    db.add(PipelineState(school_id=2, owner_id=1, stage=PipelineStage.CONTACTED))
    db.add(CampaignSchool(campaign_id=1, school_id=3, stage_at_move="not_contacted"))
    db.commit()
    yield db
    db.close()


def call(session, **overrides):
    """Direct endpoint call: FastAPI's Query(...) defaults are sentinel
    objects outside HTTP, so every parameter is passed explicitly."""
    kwargs = dict(q=None, status="all", campaign_id=None, sort="name:asc", page=1, page_size=50)
    kwargs.update(overrides)
    return directory(session=session, **kwargs)


def by_name(result):
    return {item.name: item for item in result.items}


def test_directory_shows_everyone_with_their_assignment(session):
    result = call(session)

    assert result.register_total == result.total == 3
    assert result.counts == {"available": 1, "pipeline": 1, "campaign": 1}
    items = by_name(result)
    assert items["SP AVAILABLE"].status == "available"
    assert items["SP PURSUED"].status == "pipeline" and items["SP PURSUED"].stage == "contacted"
    assert items["SP PARKED"].status == "campaign" and items["SP PARKED"].campaign_name == "September wave"


def test_directory_status_and_search_filters(session):
    assert set(by_name(call(session, status="available"))) == {"SP AVAILABLE"}
    assert set(by_name(call(session, status="pipeline"))) == {"SP PURSUED"}
    assert set(by_name(call(session, status="campaign"))) == {"SP PARKED"}
    assert set(by_name(call(session, campaign_id=1))) == {"SP PARKED"}
    assert set(by_name(call(session, q="opole"))) == {"SP PARKED"}
    # Counts describe the whole register regardless of the active filter.
    assert call(session, status="pipeline").counts["available"] == 1
