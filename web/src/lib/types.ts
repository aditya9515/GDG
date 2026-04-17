export type DomainKind = 'DISASTER_RELIEF' | 'HEALTHCARE_EMERGENCY'
export type CategoryKind =
  | 'RESCUE'
  | 'MEDICAL'
  | 'WATER'
  | 'SANITATION'
  | 'SHELTER'
  | 'FOOD'
  | 'ESSENTIAL_ITEMS'
  | 'LOGISTICS'
  | 'PROTECTION'
  | 'ELECTRICITY_TELECOM'
  | 'MISSING_PERSONS'
  | 'MENTAL_HEALTH'
  | 'ANIMAL_LIVESTOCK'
  | 'COORDINATION'
export type UrgencyKind = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'
export type CaseStatus = 'NEW' | 'EXTRACTED' | 'NEEDS_REVIEW' | 'SCORED' | 'ASSIGNED' | 'MERGED' | 'CLOSED'
export type DuplicateStatus = 'NONE' | 'POSSIBLE_DUPLICATE' | 'LIKELY_DUPLICATE'
export type AvailabilityStatus = 'AVAILABLE' | 'ON_MISSION' | 'OFFLINE'
export type AssignmentStatus = 'PROPOSED' | 'CONFIRMED' | 'IN_PROGRESS' | 'COMPLETED'
export type LocationConfidence = 'EXACT' | 'APPROXIMATE' | 'UNKNOWN'
export type InfoTokenType =
  | 'NEED'
  | 'TEAM_CAPABILITY'
  | 'RESOURCE_CAPABILITY'
  | 'LOCATION_HINT'
  | 'AVAILABILITY_UPDATE'
export type IngestionKind = 'MANUAL_TEXT' | 'CSV' | 'PDF' | 'IMAGE'
export type IngestionStatus = 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
export type OrgRole = 'HOST' | 'INCIDENT_COORDINATOR' | 'MEDICAL_COORDINATOR' | 'LOGISTICS_LEAD' | 'VIEWER'
export type MembershipStatus = 'INVITED' | 'ACTIVE' | 'DISABLED' | 'REMOVED'
export type GraphRunStatus = 'RUNNING' | 'WAITING_FOR_USER' | 'WAITING_FOR_CONFIRMATION' | 'COMMITTED' | 'FAILED'
export type DraftRecordType = 'INCIDENT' | 'TEAM' | 'RESOURCE' | 'DISPATCH' | 'INFO_TOKEN'

export interface GeoPoint {
  lat: number
  lng: number
}

export interface ResourceNeed {
  resource_type: string
  quantity: number | null
  unit: string | null
}

export interface DataQuality {
  missing_location: boolean
  missing_quantity: boolean
  needs_followup_questions: string[]
}

export interface IncidentExtraction {
  domain: DomainKind
  category: CategoryKind
  subcategory: string
  urgency: UrgencyKind
  people_affected: number | null
  vulnerable_groups: string[]
  location_text: string
  time_to_act_hours: number | null
  required_resources: ResourceNeed[]
  notes_for_dispatch: string
  data_quality: DataQuality
  confidence: number
}

export interface PriorityRationale {
  life_threat_score: number
  time_sensitivity_score: number
  vulnerability_score: number
  scale_score: number
  sector_severity_score: number
  access_constraint_score: number
  final_score: number
  final_urgency: UrgencyKind
  cap_reason: string | null
}

export interface RouteSummary {
  provider: string
  distance_km: number | null
  duration_minutes: number | null
  polyline: string | null
}

export interface RecommendationReason {
  entity_id: string
  label: string
  capability_fit: number
  eta_score: number
  availability: number
  capacity_ok: number
  workload_balance: number
  reliability: number
}

export interface Recommendation {
  team_id: string | null
  volunteer_ids: string[]
  resource_ids: string[]
  resource_allocations: ResourceNeed[]
  match_score: number
  eta_minutes: number | null
  route_summary: RouteSummary | null
  reasons: RecommendationReason[]
}

export interface DuplicateLink {
  link_id: string
  case_id: string
  other_case_id: string
  similarity: number
  decision: DuplicateStatus
  geo_distance_km: number | null
}

export interface CaseEvent {
  event_id: string
  case_id: string
  event_type: string
  actor_uid: string
  timestamp: string
  payload: Record<string, unknown>
}

export interface InfoToken {
  token_id: string
  token_type: InfoTokenType
  source_kind: string
  source_ref: string
  summary: string
  normalized_text: string
  redacted_text: string
  language: string
  confidence: number
  case_id: string | null
  linked_entity_type: string | null
  linked_entity_id: string | null
  category: string | null
  urgency_hint: string | null
  location_text: string | null
  geo: GeoPoint | null
  location_confidence: LocationConfidence
  quantity: number | null
  unit: string | null
  time_window_hours: number | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface EvidenceItem {
  evidence_id: string
  source_kind: string
  filename: string
  content_type: string
  size_bytes: number
  storage_path: string
  uploaded_by: string
  uploaded_at: string
  status: string
  incident_id: string | null
  linked_entity_type: string | null
  linked_entity_id: string | null
  extracted_text: string | null
  preview_url: string | null
  notes: string[]
}

export interface CaseRecord {
  case_id: string
  incident_id: string | null
  raw_input: string
  source_channel: string
  status: CaseStatus
  extracted_json: IncidentExtraction | null
  priority_score: number | null
  priority_rationale: PriorityRationale | null
  urgency: UrgencyKind
  location_text: string
  geo: GeoPoint | null
  location_confidence: LocationConfidence
  duplicate_status: DuplicateStatus
  created_at: string
  created_by: string
  notes: string[]
  info_token_ids: string[]
  evidence_ids: string[]
  recommended_dispatches: Recommendation[]
  final_dispatch_id: string | null
  hazard_type: string | null
  source_languages: string[]
  source_hash?: string | null
}

export interface Organization {
  org_id: string
  name: string
  host_uid: string
  host_email: string | null
  status: string
  settings: Record<string, unknown>
  created_at: string
}

export interface OrgMembership {
  membership_id: string
  org_id: string
  uid: string | null
  email: string
  role: OrgRole
  status: MembershipStatus
  invited_by: string | null
  joined_at: string | null
  disabled_at: string | null
}

export interface OrgInvite {
  invite_id: string
  org_id: string
  email: string
  role: OrgRole
  invited_by: string
  status: MembershipStatus
  created_at: string
  accepted_at: string | null
}

export interface RecordDraft {
  draft_id: string
  draft_type: DraftRecordType
  title: string
  payload: Record<string, unknown>
  confidence: number
  warnings: string[]
  frozen: boolean
  removed: boolean
  source_row_index?: number | null
  changed_fields?: string[]
  skipped_reason?: string | null
  display_fields?: Record<string, unknown>
  map_status?: LocationConfidence
}

export interface UserQuestion {
  question_id: string
  question: string
  field: string | null
  required: boolean
}

export interface SourceArtifact {
  artifact_id: string
  org_id: string
  source_kind: string
  filename: string | null
  text: string
  docling_markdown: string | null
  docling_json: Record<string, unknown>
  parse_status: string
  parse_warnings: string[]
  detected_languages: string[]
  ocr_used: boolean
}

export interface GraphRun {
  run_id: string
  org_id: string
  graph_name: string
  status: GraphRunStatus
  created_by: string
  created_at: string
  updated_at: string
  source_artifacts: SourceArtifact[]
  drafts: RecordDraft[]
  user_questions: UserQuestion[]
  user_answers: Record<string, string>
  needs_user_input: boolean
  next_action: string | null
  committed_record_ids: string[]
  error_message: string | null
}

export interface AiStatusResponse {
  provider_mode: string
  gemini_enabled: boolean
  gemini_configured: boolean
  ollama_base_url: string
  ollama_model: string
  ollama_reachable: boolean
  fallback_order: string[]
}

export interface Team {
  team_id: string
  display_name: string
  capability_tags: string[]
  member_ids: string[]
  service_radius_km: number
  base_label: string
  base_geo: GeoPoint | null
  current_label: string | null
  current_geo: GeoPoint | null
  availability_status: AvailabilityStatus
  active_dispatches: number
  reliability_score: number
  evidence_ids: string[]
  notes: string[]
  created_at?: string
  updated_at?: string
}

export interface Volunteer {
  volunteer_id: string
  team_id: string | null
  display_name: string
  role_tags: string[]
  skills: string[]
  home_base_label: string
  home_base: GeoPoint | null
  current_geo: GeoPoint | null
  availability_status: AvailabilityStatus
  max_concurrent_assignments: number
  active_assignments: number
  reliability_score: number
  last_active_iso: string
  created_at?: string
  updated_at?: string
}

export interface ResourceInventory {
  resource_id: string
  owning_team_id: string | null
  resource_type: string
  quantity_available: number
  location_label: string
  location: GeoPoint | null
  current_label: string | null
  current_geo: GeoPoint | null
  constraints: string[]
  evidence_ids: string[]
  image_url: string | null
  created_at?: string
  updated_at?: string
}

export interface AssignmentDecision {
  assignment_id: string
  case_id: string
  incident_id: string | null
  team_id: string | null
  volunteer_ids: string[]
  resource_ids: string[]
  resource_allocations: ResourceNeed[]
  match_score: number
  eta_minutes: number | null
  route_summary: RouteSummary | null
  status: AssignmentStatus
  confirmed_by: string
  confirmed_at: string
}

export interface IngestionJob {
  job_id: string
  kind: IngestionKind
  target: string
  filename: string
  status: IngestionStatus
  created_by: string
  created_at: string
  completed_at: string | null
  evidence_id: string | null
  row_count: number
  success_count: number
  warning_count: number
  produced_case_ids: string[]
  produced_token_ids: string[]
  error_message: string | null
}

export interface UploadRegistrationResponse {
  evidence_item: EvidenceItem
  upload_mode: string
  upload_url: string | null
  storage_path: string
}

export interface DashboardSummary {
  total_cases: number
  open_cases: number
  critical_cases: number
  assigned_today: number
  pending_duplicates: number
  median_time_to_assign_minutes: number
  average_confidence: number
  mapped_cases: number
  mapped_resources: number
  mapped_teams: number
  active_dispatches: number
}

export interface CaseDetailResponse {
  case: CaseRecord
  events: CaseEvent[]
  duplicate_candidates: DuplicateLink[]
  tokens: InfoToken[]
  evidence_items: EvidenceItem[]
  dispatches: AssignmentDecision[]
}

export interface EvalRunSummary {
  run_id: string
  created_at: string
  extraction_accuracy: number
  critical_mislabels: number
  duplicate_precision: number
  notes: string
}

export interface AuthSessionResponse {
  uid: string
  email: string | null
  role: string
  enabled: boolean
  team_scope: string[]
  auth_mode: string
  repository_backend: string
  organizations: Organization[]
  memberships: OrgMembership[]
  default_org_id: string | null
  active_org_id: string | null
  is_host: boolean
}

export interface ResetOrganizationDataResponse {
  status: string
  org_id: string
  deleted_counts: Record<string, number>
  request_id: string
}
