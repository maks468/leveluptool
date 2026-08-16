"""Campaign containers -- named batches of schools parked out of the
pipeline. Pure storage/tracking: nothing here sends anything (see the
Campaign model docstring for the one-place invariant this enforces).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from levelup.api.v1.schemas import (
    CampaignCreate,
    CampaignDetailOut,
    CampaignOut,
    CampaignSchoolOut,
    MoveToCampaignRequest,
    MoveToCampaignResult,
)
from levelup.core.db import get_session
from levelup.core.security import get_current_user
from levelup.models.campaign import Campaign, CampaignSchool
from levelup.models.score import CurrentScore, SchoolScore
from levelup.models.user import User
from levelup.services.pipeline.campaigns import (
    move_to_campaign,
    return_all_to_pipeline,
    return_to_pipeline,
)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _campaign_out(campaign: Campaign, school_count: int) -> CampaignOut:
    return CampaignOut(
        id=campaign.id, name=campaign.name, created_at=campaign.created_at, school_count=school_count
    )


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(
    body: CampaignCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Campaign name must not be empty")
    if session.query(Campaign).filter(func.lower(Campaign.name) == name.lower()).one_or_none():
        raise HTTPException(409, f'A campaign named "{name}" already exists')
    campaign = Campaign(name=name, owner_id=user.id)
    session.add(campaign)
    session.commit()
    return _campaign_out(campaign, school_count=0)


@router.get("", response_model=list[CampaignOut])
def list_campaigns(session: Session = Depends(get_session)):
    counts = dict(
        session.query(CampaignSchool.campaign_id, func.count(CampaignSchool.id))
        .group_by(CampaignSchool.campaign_id)
        .all()
    )
    campaigns = session.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return [_campaign_out(c, counts.get(c.id, 0)) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignDetailOut)
def get_campaign(campaign_id: int, session: Session = Depends(get_session)):
    campaign = session.query(Campaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(404, "Campaign not found")

    memberships = (
        session.query(CampaignSchool)
        .options(joinedload(CampaignSchool.school))
        .filter(CampaignSchool.campaign_id == campaign.id)
        .order_by(CampaignSchool.added_at.desc(), CampaignSchool.id.desc())
        .all()
    )
    scores = dict(
        session.query(CurrentScore.school_id, SchoolScore.total_score)
        .join(SchoolScore, SchoolScore.id == CurrentScore.score_id)
        .filter(CurrentScore.school_id.in_([m.school_id for m in memberships]))
        .all()
    )
    schools = [
        CampaignSchoolOut(
            id=m.school.id,
            name=m.school.name,
            level=m.school.level.value,
            voivodeship=m.school.voivodeship,
            city=m.school.city,
            is_private=m.school.is_private,
            student_count=m.school.student_count,
            name_disambiguator=m.school.name_disambiguator,
            score=scores.get(m.school_id),
            stage_at_move=m.stage_at_move,
            added_at=m.added_at,
        )
        for m in memberships
    ]
    return CampaignDetailOut(
        id=campaign.id,
        name=campaign.name,
        created_at=campaign.created_at,
        school_count=len(schools),
        schools=schools,
    )


@router.post("/{campaign_id}/schools", response_model=MoveToCampaignResult)
def move_schools(
    campaign_id: int,
    body: MoveToCampaignRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Moves the given pipeline schools into this campaign -- move, not
    copy: their PipelineState rows are deleted in the same transaction.
    Ids not currently in the pipeline are reported back, never moved."""
    campaign = session.query(Campaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    if not body.school_ids:
        raise HTTPException(400, "Provide at least one school id")
    result = move_to_campaign(session, campaign, body.school_ids, actor_id=user.id)
    return MoveToCampaignResult(**result)


@router.post("/{campaign_id}/schools/{school_id}/return", response_model=MoveToCampaignResult)
def return_school(
    campaign_id: int,
    school_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """The one way out of a campaign: back into the pipeline at the stage
    the school held when it was parked."""
    membership = (
        session.query(CampaignSchool)
        .filter_by(campaign_id=campaign_id, school_id=school_id)
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(404, "School is not in this campaign")
    return_to_pipeline(session, membership, actor_id=user.id)
    return MoveToCampaignResult(moved=1, not_in_pipeline=0, already_in_campaign=0)


@router.post("/{campaign_id}/return-all", response_model=MoveToCampaignResult)
def return_all_schools(
    campaign_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Empties the whole campaign back into the pipeline -- every school at
    the stage it held when it was parked. The empty container survives."""
    campaign = session.query(Campaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    moved = return_all_to_pipeline(session, campaign, actor_id=user.id)
    return MoveToCampaignResult(moved=moved, not_in_pipeline=0, already_in_campaign=0)


@router.delete("/{campaign_id}", response_model=CampaignOut)
def delete_campaign(campaign_id: int, session: Session = Depends(get_session)):
    """Deletes the container AND its memberships. The schools return to
    being plain Library rows -- NOT to the pipeline -- so deleting a
    finished campaign doesn't flood the working queue; their activity log
    still records the whole history."""
    campaign = session.query(Campaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    school_count = session.query(CampaignSchool).filter_by(campaign_id=campaign.id).count()
    out = _campaign_out(campaign, school_count)
    session.delete(campaign)  # cascades to memberships (delete-orphan)
    session.commit()
    return out
