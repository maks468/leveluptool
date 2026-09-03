export type SchoolLevel = "primary" | "liceum" | "technikum" | "branzowa_i" | "branzowa_ii" | "policealna"

export const LEVEL_LABELS: Record<SchoolLevel, string> = {
  primary: "Primary",
  liceum: "Liceum",
  technikum: "Technikum",
  branzowa_i: "Branżowa I",
  branzowa_ii: "Branżowa II",
  policealna: "Policealna",
}
export type OwnershipSubtype = "niepubliczna" | "spoleczna" | "miedzynarodowa"
export type LanguageOrientation = "bilingual" | "english_first_plus_extra" | "standard_english"
export type RubricType = "primary" | "secondary"

export type PipelineStage =
  | "not_contacted"
  | "contacted"
  | "responded"
  | "meeting_booked"
  | "meeting_held"
  | "next_step_agreed"
  | "won"
  | "lost"

export const PIPELINE_STAGES: PipelineStage[] = [
  "not_contacted",
  "contacted",
  "responded",
  "meeting_booked",
  "meeting_held",
  "next_step_agreed",
  "won",
  "lost",
]

export const STAGE_LABELS: Record<PipelineStage, string> = {
  not_contacted: "Not contacted",
  contacted: "Contacted",
  responded: "Responded",
  meeting_booked: "Meeting booked",
  meeting_held: "Meeting held",
  next_step_agreed: "Next step agreed",
  won: "Won",
  lost: "Lost",
}

export interface CriterionScore {
  points: number
  max: number
  basis: "verified" | "unknown"
}

export interface Score {
  rubric_type: RubricType
  rubric_version: string
  total_score: number | null
  criterion_breakdown: Record<string, CriterionScore>
  computed_at: string
}

export type EnrichmentLevel = "complete" | "successful" | "partial" | "basic" | "not_enriched"

export interface School {
  id: number
  rspo_id: string
  name: string
  level: SchoolLevel
  voivodeship: string | null
  city: string | null
  is_private: boolean | null
  ownership_subtype: OwnershipSubtype | null
  ownership_subtype_verified: boolean
  student_count: number | null
  is_adult_education: boolean
  is_branch: boolean
  has_grades_7_8: boolean | null
  website_url: string | null
  /** null = straight from RSPO's raw field, never corrected. "manual" =
   * user-entered override; "enrichment" = auto-discovered via search --
   * either one survives future RSPO re-imports. */
  website_url_source: "rspo_structured_field" | "rspo_name_match" | "enrichment" | "manual" | null
  language_orientation: LanguageOrientation | null
  school_profile: string | null
  director_name: string | null
  english_teacher_name: string | null
  specialty: string | null
  /** Extra bit that makes a non-unique "name, city" unique (parent complex,
   * or an "RSPO <id>" fallback). Null when name+city is already unique. */
  name_disambiguator: string | null
  enrichment_level: EnrichmentLevel
  is_active: boolean
  in_pipeline: boolean
  /** The campaign container this school is parked in, if any -- a school
   * lives in exactly one place: Library only, pipeline, or one campaign. */
  campaign_name: string | null
  stage: PipelineStage | null
  next_action_note: string | null
  next_action_date: string | null
  score: Score | null
}

export interface PipelineSchool extends School {
  stage: PipelineStage
  entered_pipeline_at: string
  stage_updated_at: string
  /** Single best contact email for outreach (personal decision-maker, else office). */
  best_email: string | null
  /** How this school entered the pipeline (filter snapshot / "Manually selected"). */
  pull_criteria: string | null
}

export interface QueueEntry extends PipelineSchool {
  last_activity_at: string | null
  queue_reason: string
}

export interface MapSchool {
  id: number
  name: string
  city: string | null
  latitude: number
  longitude: number
  stage: PipelineStage
  score: number | null
  director_name: string | null
  english_teacher_name: string | null
  last_activity_at: string | null
  last_note: string | null
}

export interface AutoEnrichSettings {
  enabled: boolean
  schools_per_run: number
  interval_minutes: number
  last_run_at: string | null
  last_run_found_count: number | null
}

export interface FunnelStage {
  stage: PipelineStage
  reached: number
}

export interface ScoreBand {
  band: string
  total: number
  won: number
  lost: number
  win_rate: number | null
}

export interface VoivodeshipConversion {
  voivodeship: string
  total: number
  won: number
  lost: number
  win_rate: number | null
}

export interface FunnelReport {
  stage_reached: FunnelStage[]
  lost_count: number
  win_rate: number | null
  response_rate: number | null
  avg_score_won: number | null
  avg_score_lost: number | null
  score_bands: ScoreBand[]
  voivodeship_conversion: VoivodeshipConversion[]
}

export interface DataQualityReport {
  library_total: number
  library_enriched_attempted: number
  library_never_attempted: number
  library_verified_contact: number
  library_partial_contact: number
  pipeline_total: number
  pipeline_active_total: number
  pipeline_missing_verified_contact: number
  pipeline_partial_contact: number
  pipeline_never_enriched: number
  pipeline_no_follow_up: number
  pipeline_stale_14d: number
  enrichment_items_total: number
  enrichment_items_success: number
  enrichment_items_failed: number
  enrichment_success_rate: number | null
}

export interface SchoolListResponse {
  total: number
  page: number
  page_size: number
  items: School[]
}

export interface PipelineListResponse {
  total: number
  page: number
  page_size: number
  stage_counts: Partial<Record<PipelineStage, number>>
  items: PipelineSchool[]
}

export interface CityFacet {
  city: string
  count: number
}

export interface VoivodeshipFacet {
  voivodeship: string
  count: number
}

export type FacetScope = "library" | "pipeline" | "register"

export type DirectoryStatus = "available" | "pipeline" | "campaign"

/** One school in the full-register Directory, with its current assignment. */
/** Where the last enrichment stopped short for a school, or null when
 * nothing failed (teacher email found) / never enriched. */
export type EnrichmentIssue =
  | "website_missing"
  | "website_unreachable"
  | "website_rejected"
  | "no_staff_page_found"
  | "teacher_not_published"
  | "teacher_email_not_published"

export interface DirectoryEntry {
  id: number
  name: string
  name_disambiguator: string | null
  level: SchoolLevel
  voivodeship: string | null
  city: string | null
  score: number | null
  status: DirectoryStatus
  campaign_name: string | null
  stage: PipelineStage | null
  enrichment_issue: EnrichmentIssue | null
}

export interface DirectoryListResponse {
  total: number
  page: number
  page_size: number
  register_total: number
  counts: Record<DirectoryStatus, number>
  items: DirectoryEntry[]
}

export interface DashboardSummary {
  library_total: number
  /** The available pool -- register minus pipeline minus campaigns. */
  available_total: number
  library_by_level: Partial<Record<SchoolLevel, number>>
  scored_total: number
  unscored_total: number
  pipeline_total: number
  /** Schools parked in campaign containers (see Campaign). */
  campaign_schools_total: number
  stage_counts: Partial<Record<PipelineStage, number>>
  high_score_not_contacted: number
}

export interface RecentActivityEntry {
  id: number
  school_id: number
  school_name: string
  school_city: string | null
  activity_type: string
  from_stage: string | null
  to_stage: string | null
  note: string | null
  occurred_at: string
}

export type ContactQuality = "failed" | "partial" | "verified"

export interface SchoolContact {
  id: number
  contact_type: "director" | "english_coordinator" | "general"
  person_name: string | null
  email: string | null
  phone: string | null
  source_url: string | null
  contact_quality: ContactQuality
  captured_at: string
}

/** One URL an enrichment run actually fetched, or one search query it ran --
 * both are "sources checked" so the whole trail stays visible after the fact. */
export interface EnrichmentSource {
  url?: string
  query?: string
  status: "ok" | "unreachable" | "search_returned_no_results"
  found_via_search?: string
  /** True when this page was loaded via the headless-browser fallback
   * (a JS-rendered site) rather than a plain fetch. */
  rendered?: boolean
}

export interface ActivityLogEntry {
  id: number
  school_id: number
  actor_id: number | null
  activity_type: string
  from_stage: string | null
  to_stage: string | null
  note: string | null
  metadata_json: Record<string, unknown>
  occurred_at: string
}

export interface EnrichmentJobItem {
  school_id: number
  school_name: string
  school_city: string | null
  status: "pending" | "running" | "success" | "failed" | "cancelled"
  error_message: string | null
}

export interface EnrichmentJob {
  id: number
  status: "pending" | "running" | "done" | "cancelled"
  requested_at: string
  is_automatic: boolean
  cancel_requested: boolean
  items: EnrichmentJobItem[]
}

export interface LibraryFilters {
  voivodeship: string | null
  city: string | null
  school_type: "all" | "primary" | "secondary" | "liceum" | "technikum" | "vocational"
  ownership_public: boolean
  ownership_private: boolean
  ownership_subtype: OwnershipSubtype[]
  ownership_include_unverified: boolean
  students_min: number | null
  students_max: number | null
  students_include_unknown: boolean
  score_min: number | null
  score_max: number | null
  score_include_unscored: boolean
  /** What enrichment has found for the school -- the same levels the
   * Enrichment column badges show, plus the "any level"/"no level" split,
   * and separately whether enrichment has ever run against it at all
   * ("attempted"/"never_attempted", regardless of what it found). */
  enrichment: EnrichmentFilter
}

export type EnrichmentFilter =
  | "all"
  | EnrichmentLevel
  | "complete"
  /** Deprecated alias of "complete": the ENGLISH TEACHER's own email was found --
   * the top-priority contact, always ranked above the director's. */
  | "successful_teacher"
  | "enriched"
  | "attempted"
  | "never_attempted"

/** What the Pipeline's enrichment dropdown can send: the four levels plus
 * the teacher-email refinement. */
export type PipelineEnrichmentFilter = EnrichmentLevel | "successful_teacher"


export type SavedViewScope = "library" | "pipeline"

export interface SavedView {
  id: number
  name: string
  scope: SavedViewScope
  filters_json: Record<string, unknown>
  sort: string | null
  result_limit: number | null
  is_favorite: boolean
  created_at: string
  updated_at: string
}

export interface Tag {
  id: number
  name: string
  color: string
}

/** A named batch of schools parked OUT of the pipeline -- pure storage for
 * tracking which schools went into which outreach batch, so none is ever
 * doubled. Nothing is sent from here. */
export interface Campaign {
  id: number
  name: string
  /** Free-form note about what this batch is ("wysyłka wrzesień, template B"). */
  description: string | null
  created_at: string
  school_count: number
}

export interface CampaignSchoolEntry {
  id: number
  name: string
  level: SchoolLevel
  voivodeship: string | null
  city: string | null
  is_private: boolean | null
  student_count: number | null
  name_disambiguator: string | null
  score: number | null
  /** Pipeline stage the school held at the moment it was parked here. */
  stage_at_move: PipelineStage
  added_at: string
}

export interface CampaignDetail extends Campaign {
  schools: CampaignSchoolEntry[]
}

export const TAG_COLORS = ["slate", "indigo", "green", "red", "amber", "cyan", "violet", "blue", "purple"] as const

export interface SchoolSearchResult {
  id: number
  name: string
  city: string | null
  voivodeship: string | null
  level: SchoolLevel
  score: number | null
  in_pipeline: boolean
}

export const DEFAULT_LIBRARY_FILTERS: LibraryFilters = {
  voivodeship: null,
  city: null,
  school_type: "all",
  ownership_public: true,
  ownership_private: true,
  ownership_subtype: ["niepubliczna", "spoleczna", "miedzynarodowa"],
  ownership_include_unverified: true,
  students_min: null,
  students_max: null,
  students_include_unknown: true,
  score_min: null,
  score_max: null,
  score_include_unscored: true,
  enrichment: "all",
}
