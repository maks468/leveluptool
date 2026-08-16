"""Resets the CRM workflow back to a freshly-imported state.

Deliberately scoped: deletes everything that represents *work done in the
tool* (pipeline membership, activity history, enrichment jobs and the
contacts/names they found, tags, saved views) but never touches the
imported school registry itself (`schools`' core RSPO-sourced fields),
scores, or Perspektywy rankings -- those took a real import/scoring/crawl
run to produce and re-deriving them isn't the point of a "start over on
my outreach work" reset.

`director_name`/`english_teacher_name` on School are themselves enrichment
output (whether from the RSPO detail-API backfill or website scraping), so
they're cleared too -- otherwise the Library would keep showing a name
with no underlying SchoolContact record or enrichment history behind it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from levelup.models.campaign import Campaign, CampaignSchool
from levelup.models.crm import SavedView, SchoolTag, Tag
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityLog, ActivityType, PipelineState
from levelup.models.school import School

# Activity that records OUTREACH -- what you did about a school. Cleared
# alongside the pipeline itself, because a stage change or a call note is
# only meaningful as part of the pursuit being cleared.
OUTREACH_ACTIVITY_TYPES = (
    ActivityType.PULLED_INTO_PIPELINE.value,
    ActivityType.REMOVED_FROM_PIPELINE.value,
    ActivityType.STAGE_CHANGED.value,
    ActivityType.NOTE.value,
    ActivityType.EMAIL_SENT.value,
    ActivityType.EMAIL_OPENED.value,
    ActivityType.REMINDER_SCHEDULED.value,
)

# Everything else on the activity log describes the SCHOOL RECORD rather
# than the outreach -- what enrichment found, an ownership subtype that got
# confirmed, a website URL someone corrected. That survives a pipeline
# clear: it's the audit trail behind data still sitting in the Library.
# (ActivityType.ENRICHMENT_COMPLETED, OWNERSHIP_SUBTYPE_CONFIRMED,
# WEBSITE_URL_CORRECTED.)


def reset_pipeline_workflow(session: Session) -> dict[str, int]:
    counts = {
        "school_contacts_removed": session.query(SchoolContact).delete(synchronize_session=False),
        "enrichment_job_items_removed": session.query(EnrichmentJobItem).delete(synchronize_session=False),
        "enrichment_jobs_removed": session.query(EnrichmentJob).delete(synchronize_session=False),
        "school_tags_removed": session.query(SchoolTag).delete(synchronize_session=False),
        "tags_removed": session.query(Tag).delete(synchronize_session=False),
        "activity_log_removed": session.query(ActivityLog).delete(synchronize_session=False),
        "saved_views_removed": session.query(SavedView).delete(synchronize_session=False),
        "pipeline_schools_removed": session.query(PipelineState).delete(synchronize_session=False),
        # Campaigns are parked outreach batches -- workflow state, so the
        # full reset clears them. (clear_pipeline below deliberately does
        # NOT: parked batches are the record that those schools were already
        # contacted, which must outlive a pipeline rebuild.)
        "campaign_schools_removed": session.query(CampaignSchool).delete(synchronize_session=False),
        "campaigns_removed": session.query(Campaign).delete(synchronize_session=False),
    }
    counts["schools_uncontacted_reset"] = (
        session.query(School)
        .filter(School.director_name.isnot(None) | School.english_teacher_name.isnot(None))
        .update({School.director_name: None, School.english_teacher_name: None}, synchronize_session=False)
    )
    session.commit()
    return counts


def clear_pipeline(session: Session) -> dict[str, int]:
    """Empties the pipeline without touching a single piece of enrichment.

    The narrower counterpart to reset_pipeline_workflow above: that one
    starts the whole tool over, including throwing away every contact
    enrichment ever found. Those contacts cost real crawling and LLM calls
    to produce and have nothing to do with which schools you're currently
    pursuing, so "I want to rebuild my pipeline" shouldn't require
    sacrificing them.

    Removes pipeline membership (and with it, stages and follow-ups, which
    are columns on that same row) plus the outreach half of the activity
    log. Deliberately leaves alone: SchoolContact, enrichment jobs and
    their items, the director/English-teacher names on School, tags, saved
    views, scores, rankings and the Library itself. After this, every
    school reads as never-pursued while its enrichment level, contacts and
    enrichment history stay exactly as they were -- so re-pulling a fresh
    pipeline costs nothing but the pull.
    """
    counts = {
        "activity_log_removed": session.query(ActivityLog)
        .filter(ActivityLog.activity_type.in_(OUTREACH_ACTIVITY_TYPES))
        .delete(synchronize_session=False),
        "pipeline_schools_removed": session.query(PipelineState).delete(synchronize_session=False),
    }
    counts["school_contacts_kept"] = session.query(SchoolContact).count()
    counts["activity_log_kept"] = session.query(ActivityLog).count()
    session.commit()
    return counts
