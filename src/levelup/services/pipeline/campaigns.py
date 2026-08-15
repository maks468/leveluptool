"""Moving schools between the pipeline and campaign containers.

The invariant both functions protect: a school lives in exactly ONE place
-- the Library only, the pipeline, or a single campaign. That's the whole
double-contact guarantee, so every transition here is move semantics
(delete one side, insert the other, same transaction), never copy.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from levelup.models.campaign import Campaign, CampaignSchool
from levelup.models.pipeline import ActivityType, PipelineStage, PipelineState
from levelup.services.pipeline.activity import log_activity


def move_to_campaign(
    session: Session, campaign: Campaign, school_ids: list[int], *, actor_id: int
) -> dict[str, int]:
    """Moves pipeline schools into a campaign. Only schools currently IN
    the pipeline move -- a school can only be campaigned from the working
    queue, which is also what makes the one-place invariant hold (pipeline
    membership and campaign membership are mutually exclusive by
    construction, since pull skips campaign members). Anything else in the
    id list is reported, not moved: not_in_pipeline covers both plain
    Library schools and ids that don't exist; already_in_campaign covers
    schools sitting in some campaign container (necessarily a different
    one -- they can't be in the pipeline too)."""
    requested = list(dict.fromkeys(school_ids))  # de-dupe, keep order
    states = {
        s.school_id: s
        for s in session.query(PipelineState).filter(PipelineState.school_id.in_(requested)).all()
    }
    already = {
        row.school_id
        for row in session.query(CampaignSchool.school_id)
        .filter(CampaignSchool.school_id.in_(requested))
        .all()
    }

    moved = 0
    for school_id in requested:
        state = states.get(school_id)
        if state is None or school_id in already:
            continue
        session.add(
            CampaignSchool(
                campaign_id=campaign.id,
                school_id=school_id,
                stage_at_move=state.stage.value,
            )
        )
        session.delete(state)
        log_activity(
            session,
            school_id=school_id,
            activity_type=ActivityType.MOVED_TO_CAMPAIGN.value,
            actor_id=actor_id,
            note=f'Moved to campaign "{campaign.name}" (was {state.stage.value})',
            metadata={"campaign_id": campaign.id, "stage_at_move": state.stage.value},
        )
        moved += 1

    session.commit()
    return {
        "moved": moved,
        "not_in_pipeline": len([sid for sid in requested if sid not in states and sid not in already]),
        "already_in_campaign": len([sid for sid in requested if sid in already]),
    }


def return_to_pipeline(session: Session, membership: CampaignSchool, *, actor_id: int) -> None:
    """The one way out of a campaign: back to the pipeline, at the stage
    the school had when it was moved. Restoring the stage (rather than
    resetting to not_contacted) is what keeps the history honest -- a
    school that was CONTACTED before the campaign is still contacted."""
    try:
        stage = PipelineStage(membership.stage_at_move)
    except ValueError:  # a stage value from a future/older schema -- be safe
        stage = PipelineStage.NOT_CONTACTED
    campaign_name = membership.campaign.name
    session.add(
        PipelineState(
            school_id=membership.school_id,
            owner_id=actor_id,
            stage=stage,
            pull_criteria=f'Returned from campaign "{campaign_name}"',
        )
    )
    log_activity(
        session,
        school_id=membership.school_id,
        activity_type=ActivityType.PULLED_INTO_PIPELINE.value,
        actor_id=actor_id,
        note=f'Returned to pipeline from campaign "{campaign_name}" (stage restored: {stage.value})',
        metadata={"campaign_id": membership.campaign_id},
    )
    session.delete(membership)
    session.commit()
