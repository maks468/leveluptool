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

from levelup.models.crm import SavedView, SchoolTag, Tag
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityLog, PipelineState
from levelup.models.school import School


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
    }
    counts["schools_uncontacted_reset"] = (
        session.query(School)
        .filter(School.director_name.isnot(None) | School.english_teacher_name.isnot(None))
        .update({School.director_name: None, School.english_teacher_name: None}, synchronize_session=False)
    )
    session.commit()
    return counts
