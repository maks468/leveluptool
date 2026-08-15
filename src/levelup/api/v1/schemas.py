from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_serializer


def _stamp_utc(value: datetime | None) -> str | None:
    """Every DateTime column in this app is populated either via
    datetime.now(timezone.utc) or SQLite's CURRENT_TIMESTAMP (also UTC),
    but comes back from the DB naive. Serialized without a 'Z'/offset, a
    JS Date on the frontend parses it as LOCAL time, not UTC -- silently
    shifting every displayed/compared timestamp by the browser's UTC
    offset. Stamp UTC explicitly before it goes over the wire."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rubric_type: str
    rubric_version: str
    total_score: int | None
    criterion_breakdown: dict
    computed_at: datetime

    @field_serializer("computed_at")
    def _ser_computed_at(self, v: datetime) -> str:
        return _stamp_utc(v)


class SchoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rspo_id: str
    name: str
    level: str
    voivodeship: str | None
    city: str | None
    is_private: bool | None
    ownership_subtype: str | None
    ownership_subtype_verified: bool
    student_count: int | None
    is_adult_education: bool
    is_branch: bool
    has_grades_7_8: bool | None
    website_url: str | None
    website_url_source: str | None
    language_orientation: str | None
    school_profile: str | None
    director_name: str | None
    english_teacher_name: str | None
    specialty: str | None
    name_disambiguator: str | None
    enrichment_level: str
    is_active: bool
    in_pipeline: bool
    # The campaign container this school is parked in, if any -- surfaced
    # everywhere schools are listed so "where does this school live" (Library
    # only / pipeline / one campaign) is always answerable at a glance.
    campaign_name: str | None = None
    stage: str | None
    next_action_note: str | None
    next_action_date: datetime | None
    score: ScoreOut | None

    @field_serializer("next_action_date")
    def _ser_next_action_date(self, v: datetime | None) -> str | None:
        return _stamp_utc(v)


class WebsiteUrlUpdate(BaseModel):
    website_url: str


class CityFacetOut(BaseModel):
    city: str
    count: int


class VoivodeshipFacetOut(BaseModel):
    voivodeship: str
    count: int


class SchoolContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_type: str
    person_name: str | None
    email: str | None
    phone: str | None
    source_url: str | None
    contact_quality: str
    captured_at: datetime

    @field_serializer("captured_at")
    def _ser_captured_at(self, v: datetime) -> str:
        return _stamp_utc(v)


class SchoolListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[SchoolOut]


class PullIntoPipelineRequest(BaseModel):
    school_ids: list[int] | None = None
    filters: dict | None = None
    limit: int | None = None


class PullIntoPipelineResult(BaseModel):
    pulled_new: int
    already_in_pipeline: int
    # Skipped because they're parked in a campaign container -- getting one
    # back is the campaign page's explicit return action, never a re-pull.
    already_in_campaign: int = 0


class PipelineSchoolOut(SchoolOut):
    stage: str
    entered_pipeline_at: datetime
    stage_updated_at: datetime
    # Single best contact email for outreach (decision-maker's personal
    # address if known, else the office/secretariat mailbox).
    best_email: str | None = None
    # Human-readable snapshot of how this school entered the pipeline.
    pull_criteria: str | None = None

    @field_serializer("entered_pipeline_at", "stage_updated_at")
    def _ser_dates(self, v: datetime) -> str:
        return _stamp_utc(v)


class PipelineListOut(BaseModel):
    total: int
    page: int
    page_size: int
    stage_counts: dict[str, int]
    items: list[PipelineSchoolOut]


class StageChangeRequest(BaseModel):
    stage: str


class ActivityLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_id: int
    actor_id: int | None
    activity_type: str
    from_stage: str | None
    to_stage: str | None
    note: str | None
    metadata_json: dict
    occurred_at: datetime

    @field_serializer("occurred_at")
    def _ser_occurred_at(self, v: datetime) -> str:
        return _stamp_utc(v)


class ActivityLogCreate(BaseModel):
    note: str


class DashboardSummaryOut(BaseModel):
    library_total: int
    library_by_level: dict[str, int]
    scored_total: int
    unscored_total: int
    pipeline_total: int
    campaign_schools_total: int
    stage_counts: dict[str, int]
    high_score_not_contacted: int


class RecentActivityOut(BaseModel):
    id: int
    school_id: int
    school_name: str
    school_city: str | None
    activity_type: str
    from_stage: str | None
    to_stage: str | None
    note: str | None
    occurred_at: datetime

    @field_serializer("occurred_at")
    def _ser_occurred_at(self, v: datetime) -> str:
        return _stamp_utc(v)


class EnrichmentJobRequest(BaseModel):
    # Either an explicit set of schools (checkbox selection) OR a filter set
    # matching the current Library view -- the latter lets "enrich everything
    # matching" run over the whole filtered result, not just the visible page.
    school_ids: list[int] | None = None
    filters: dict | None = None
    limit: int | None = None


class EnrichmentJobItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    school_id: int
    school_name: str
    school_city: str | None
    status: str
    error_message: str | None


class EnrichmentJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    requested_at: datetime
    is_automatic: bool
    cancel_requested: bool
    items: list[EnrichmentJobItemOut]

    @field_serializer("requested_at")
    def _ser_requested_at(self, v: datetime) -> str:
        return _stamp_utc(v)


class SavedViewCreate(BaseModel):
    name: str
    scope: str = "library"
    filters_json: dict
    sort: str | None = None
    result_limit: int | None = None


class SavedViewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scope: str
    filters_json: dict
    sort: str | None
    result_limit: int | None
    is_favorite: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _ser_dates(self, v: datetime) -> str:
        return _stamp_utc(v)


class TagCreate(BaseModel):
    name: str
    color: str = "slate"


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str


class SchoolSearchResultOut(BaseModel):
    id: int
    name: str
    city: str | None
    voivodeship: str | None
    level: str
    score: int | None
    in_pipeline: bool


class SetFollowUpRequest(BaseModel):
    next_action_note: str | None = None
    next_action_date: datetime | None = None


class ResetConfirmRequest(BaseModel):
    confirmation: str


class ResetResultOut(BaseModel):
    school_contacts_removed: int
    enrichment_job_items_removed: int
    enrichment_jobs_removed: int
    school_tags_removed: int
    tags_removed: int
    activity_log_removed: int
    saved_views_removed: int
    pipeline_schools_removed: int
    campaign_schools_removed: int
    campaigns_removed: int
    schools_uncontacted_reset: int


class CampaignCreate(BaseModel):
    name: str


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    school_count: int

    @field_serializer("created_at")
    def _ser_created_at(self, v: datetime) -> str:
        return _stamp_utc(v)


class CampaignSchoolOut(BaseModel):
    """A school as seen inside its campaign container: the Library summary
    plus the two facts the container itself owns -- when it was parked and
    what stage it held at that moment."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level: str
    voivodeship: str | None
    city: str | None
    is_private: bool | None
    student_count: int | None
    name_disambiguator: str | None
    score: int | None
    stage_at_move: str
    added_at: datetime

    @field_serializer("added_at")
    def _ser_added_at(self, v: datetime) -> str:
        return _stamp_utc(v)


class CampaignDetailOut(CampaignOut):
    schools: list[CampaignSchoolOut]


class MoveToCampaignRequest(BaseModel):
    school_ids: list[int]


class MoveToCampaignResult(BaseModel):
    moved: int
    not_in_pipeline: int
    already_in_campaign: int


class ClearPipelineResultOut(BaseModel):
    """Reports what survived as well as what went, since the whole point of
    this action is what it DOESN'T touch."""

    pipeline_schools_removed: int
    activity_log_removed: int
    school_contacts_kept: int
    activity_log_kept: int


class QueueEntryOut(PipelineSchoolOut):
    last_activity_at: datetime | None
    queue_reason: str

    @field_serializer("last_activity_at")
    def _ser_last_activity_at(self, v: datetime | None) -> str | None:
        return _stamp_utc(v)


class MapSchoolOut(BaseModel):
    id: int
    name: str
    city: str | None
    latitude: float
    longitude: float
    stage: str
    score: int | None
    director_name: str | None
    english_teacher_name: str | None
    last_activity_at: datetime | None
    last_note: str | None

    @field_serializer("last_activity_at")
    def _ser_last_activity_at(self, v: datetime | None) -> str | None:
        return _stamp_utc(v)


class BulkStageChangeRequest(BaseModel):
    school_ids: list[int]
    stage: str


class BulkTagRequest(BaseModel):
    school_ids: list[int]


class BulkActionResult(BaseModel):
    updated: int


class AutoEnrichSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    schools_per_run: int
    interval_minutes: int
    last_run_at: datetime | None
    last_run_found_count: int | None

    @field_serializer("last_run_at")
    def _ser_last_run_at(self, v: datetime | None) -> str | None:
        return _stamp_utc(v)


class AutoEnrichSettingsUpdate(BaseModel):
    enabled: bool | None = None
    schools_per_run: int | None = None
    interval_minutes: int | None = None


class FunnelStageOut(BaseModel):
    stage: str
    reached: int


class ScoreBandOut(BaseModel):
    band: str
    total: int
    won: int
    lost: int
    win_rate: float | None


class VoivodeshipConversionOut(BaseModel):
    voivodeship: str
    total: int
    won: int
    lost: int
    win_rate: float | None


class FunnelReportOut(BaseModel):
    stage_reached: list[FunnelStageOut]
    lost_count: int
    win_rate: float | None
    response_rate: float | None
    avg_score_won: float | None
    avg_score_lost: float | None
    score_bands: list[ScoreBandOut]
    voivodeship_conversion: list[VoivodeshipConversionOut]


class DataQualityReportOut(BaseModel):
    library_total: int
    library_enriched_attempted: int
    library_never_attempted: int
    library_verified_contact: int
    library_partial_contact: int
    pipeline_total: int
    pipeline_active_total: int
    pipeline_missing_verified_contact: int
    pipeline_partial_contact: int
    pipeline_never_enriched: int
    pipeline_no_follow_up: int
    pipeline_stale_14d: int
    enrichment_items_total: int
    enrichment_items_success: int
    enrichment_items_failed: int
    enrichment_success_rate: float | None
