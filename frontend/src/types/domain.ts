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

export type EnrichmentLevel = "successful" | "partial" | "basic" | "not_enriched"

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
  language_orientation: LanguageOrientation | null
  school_profile: string | null
  director_name: string | null
  english_teacher_name: string | null
  specialty: string | null
  enrichment_level: EnrichmentLevel
  is_active: boolean
  in_pipeline: boolean
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

export type FacetScope = "library" | "pipeline"

export interface DashboardSummary {
  library_total: number
  library_by_level: Partial<Record<SchoolLevel, number>>
  scored_total: number
  unscored_total: number
  adult_education_total: number
  pipeline_total: number
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
  status: "pending" | "running" | "success" | "failed"
  error_message: string | null
}

export interface EnrichmentJob {
  id: number
  status: "pending" | "running" | "done"
  requested_at: string
  is_automatic: boolean
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
  include_adult_education: boolean
  /** Dedicated special-needs institutions: show all, only them, or exclude them. */
  special_needs: SpecialNeedsFilter
}

export type SpecialNeedsFilter = "all" | "only" | "exclude"

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
  include_adult_education: true,
  special_needs: "all",
}
