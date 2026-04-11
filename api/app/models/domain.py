from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class DomainKind(StrEnum):
    DISASTER_RELIEF = "DISASTER_RELIEF"
    HEALTHCARE_EMERGENCY = "HEALTHCARE_EMERGENCY"


class CategoryKind(StrEnum):
    RESCUE = "RESCUE"
    MEDICAL = "MEDICAL"
    WATER = "WATER"
    SANITATION = "SANITATION"
    SHELTER = "SHELTER"
    FOOD = "FOOD"
    ESSENTIAL_ITEMS = "ESSENTIAL_ITEMS"
    LOGISTICS = "LOGISTICS"
    PROTECTION = "PROTECTION"
    ELECTRICITY_TELECOM = "ELECTRICITY_TELECOM"
    MISSING_PERSONS = "MISSING_PERSONS"
    MENTAL_HEALTH = "MENTAL_HEALTH"
    ANIMAL_LIVESTOCK = "ANIMAL_LIVESTOCK"
    COORDINATION = "COORDINATION"


class UrgencyKind(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class VulnerableGroup(StrEnum):
    CHILDREN_UNDER5 = "CHILDREN_UNDER5"
    ELDERLY = "ELDERLY"
    PREGNANT = "PREGNANT"
    DISABILITY = "DISABILITY"
    CHRONIC_ILLNESS = "CHRONIC_ILLNESS"
    UNKNOWN = "UNKNOWN"
    NONE = "NONE"


class CaseStatus(StrEnum):
    NEW = "NEW"
    EXTRACTED = "EXTRACTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SCORED = "SCORED"
    ASSIGNED = "ASSIGNED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


class DuplicateStatus(StrEnum):
    NONE = "NONE"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    LIKELY_DUPLICATE = "LIKELY_DUPLICATE"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    ON_MISSION = "ON_MISSION"
    OFFLINE = "OFFLINE"


class AssignmentStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class LocationConfidence(StrEnum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    UNKNOWN = "UNKNOWN"


class InfoTokenType(StrEnum):
    NEED = "NEED"
    TEAM_CAPABILITY = "TEAM_CAPABILITY"
    RESOURCE_CAPABILITY = "RESOURCE_CAPABILITY"
    LOCATION_HINT = "LOCATION_HINT"
    AVAILABILITY_UPDATE = "AVAILABILITY_UPDATE"


class EvidenceStatus(StrEnum):
    REGISTERED = "REGISTERED"
    UPLOADED = "UPLOADED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class IngestionKind(StrEnum):
    MANUAL_TEXT = "MANUAL_TEXT"
    CSV = "CSV"
    PDF = "PDF"
    IMAGE = "IMAGE"


class IngestionStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GeoPoint(BaseModel):
    lat: float
    lng: float


class ResourceNeed(BaseModel):
    resource_type: str
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None


class DataQuality(BaseModel):
    missing_location: bool
    missing_quantity: bool
    needs_followup_questions: list[str] = Field(default_factory=list)


class IncidentExtraction(BaseModel):
    domain: DomainKind
    category: CategoryKind
    subcategory: str
    urgency: UrgencyKind
    people_affected: int | None = Field(default=None, ge=0)
    vulnerable_groups: list[VulnerableGroup] = Field(default_factory=list)
    location_text: str = ""
    time_to_act_hours: float | None = Field(default=None, ge=0)
    required_resources: list[ResourceNeed] = Field(default_factory=list)
    notes_for_dispatch: str
    data_quality: DataQuality
    confidence: float = Field(ge=0, le=1)


class PriorityRationale(BaseModel):
    life_threat_score: float = Field(ge=0, le=1)
    time_sensitivity_score: float = Field(ge=0, le=1)
    vulnerability_score: float = Field(ge=0, le=1)
    scale_score: float = Field(ge=0, le=1)
    sector_severity_score: float = Field(ge=0, le=1)
    access_constraint_score: float = Field(ge=0, le=1)
    final_score: float = Field(ge=0, le=100)
    final_urgency: UrgencyKind
    cap_reason: str | None = None


class RouteSummary(BaseModel):
    provider: str = "fallback"
    distance_km: float | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    polyline: str | None = None


class RecommendationReason(BaseModel):
    entity_id: str
    label: str
    capability_fit: float
    eta_score: float
    availability: float
    capacity_ok: float
    workload_balance: float
    reliability: float


class Recommendation(BaseModel):
    team_id: str | None = None
    volunteer_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    resource_allocations: list[ResourceNeed] = Field(default_factory=list)
    match_score: float = Field(ge=0, le=1)
    eta_minutes: int | None = Field(default=None, ge=0)
    route_summary: RouteSummary | None = None
    reasons: list[RecommendationReason] = Field(default_factory=list)


class AssignmentDecision(BaseModel):
    assignment_id: str
    case_id: str
    incident_id: str | None = None
    team_id: str | None = None
    volunteer_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    resource_allocations: list[ResourceNeed] = Field(default_factory=list)
    match_score: float = Field(ge=0, le=1)
    eta_minutes: int | None = Field(default=None, ge=0)
    route_summary: RouteSummary | None = None
    status: AssignmentStatus = AssignmentStatus.CONFIRMED
    confirmed_by: str
    confirmed_at: datetime = Field(default_factory=utcnow)


class CaseEvent(BaseModel):
    event_id: str
    case_id: str
    event_type: str
    actor_uid: str
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)


class DuplicateLink(BaseModel):
    link_id: str
    case_id: str
    other_case_id: str
    similarity: float = Field(ge=0, le=1)
    decision: DuplicateStatus
    geo_distance_km: float | None = Field(default=None, ge=0)


class TeamMember(BaseModel):
    member_id: str
    team_id: str | None = None
    display_name: str
    role_tags: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    availability_status: AvailabilityStatus
    base_geo: GeoPoint | None = None
    current_geo: GeoPoint | None = None
    active_assignments: int = 0
    reliability_score: float = Field(ge=0, le=1, default=0.7)


class Volunteer(BaseModel):
    volunteer_id: str
    team_id: str | None = None
    display_name: str
    role_tags: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    home_base_label: str
    home_base: GeoPoint | None = None
    current_geo: GeoPoint | None = None
    availability_status: AvailabilityStatus
    max_concurrent_assignments: int = 1
    active_assignments: int = 0
    reliability_score: float = Field(ge=0, le=1, default=0.7)
    last_active_iso: datetime = Field(default_factory=utcnow)


class Team(BaseModel):
    team_id: str
    display_name: str
    capability_tags: list[str] = Field(default_factory=list)
    member_ids: list[str] = Field(default_factory=list)
    service_radius_km: float = Field(default=30, ge=0)
    base_label: str
    base_geo: GeoPoint | None = None
    current_label: str | None = None
    current_geo: GeoPoint | None = None
    availability_status: AvailabilityStatus = AvailabilityStatus.AVAILABLE
    active_dispatches: int = 0
    reliability_score: float = Field(ge=0, le=1, default=0.8)
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ResourceInventory(BaseModel):
    resource_id: str
    owning_team_id: str | None = None
    resource_type: str
    quantity_available: float = Field(ge=0)
    location_label: str
    location: GeoPoint | None = None
    current_label: str | None = None
    current_geo: GeoPoint | None = None
    constraints: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    image_url: str | None = None


class EvidenceItem(BaseModel):
    evidence_id: str
    source_kind: str
    filename: str
    content_type: str
    size_bytes: int = 0
    storage_path: str
    uploaded_by: str
    uploaded_at: datetime = Field(default_factory=utcnow)
    status: EvidenceStatus = EvidenceStatus.REGISTERED
    incident_id: str | None = None
    linked_entity_type: str | None = None
    linked_entity_id: str | None = None
    extracted_text: str | None = None
    preview_url: str | None = None
    notes: list[str] = Field(default_factory=list)


class InfoToken(BaseModel):
    token_id: str
    token_type: InfoTokenType
    source_kind: str
    source_ref: str
    summary: str
    normalized_text: str
    redacted_text: str
    language: str = "en"
    confidence: float = Field(ge=0, le=1)
    case_id: str | None = None
    linked_entity_type: str | None = None
    linked_entity_id: str | None = None
    category: str | None = None
    urgency_hint: str | None = None
    location_text: str | None = None
    geo: GeoPoint | None = None
    location_confidence: LocationConfidence = LocationConfidence.UNKNOWN
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    time_window_hours: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class IngestionJob(BaseModel):
    job_id: str
    kind: IngestionKind
    target: str
    filename: str
    status: IngestionStatus = IngestionStatus.QUEUED
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    evidence_id: str | None = None
    row_count: int = 0
    success_count: int = 0
    warning_count: int = 0
    produced_case_ids: list[str] = Field(default_factory=list)
    produced_token_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None


class UserContext(BaseModel):
    uid: str
    email: str | None = None
    role: str


class UserProfile(UserContext):
    enabled: bool = True
    team_scope: list[str] = Field(default_factory=list)


class CaseRecord(BaseModel):
    case_id: str
    incident_id: str | None = None
    raw_input: str
    source_channel: str
    status: CaseStatus = CaseStatus.NEW
    extracted_json: IncidentExtraction | None = None
    priority_score: float | None = None
    priority_rationale: PriorityRationale | None = None
    urgency: UrgencyKind = UrgencyKind.UNKNOWN
    location_text: str = ""
    geo: GeoPoint | None = None
    location_confidence: LocationConfidence = LocationConfidence.UNKNOWN
    duplicate_status: DuplicateStatus = DuplicateStatus.NONE
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str = "system"
    notes: list[str] = Field(default_factory=list)
    info_token_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    recommended_dispatches: list[Recommendation] = Field(default_factory=list)
    final_dispatch_id: str | None = None
    hazard_type: str | None = None
    source_languages: list[str] = Field(default_factory=list)


class CreateCaseRequest(BaseModel):
    raw_input: str = Field(min_length=3)
    source_channel: str = "MANUAL"


class CreateCaseResponse(BaseModel):
    case_id: str
    incident_id: str | None = None
    status: CaseStatus
    request_id: str


class ExtractCaseResponse(BaseModel):
    case_id: str
    incident_id: str | None = None
    extracted: IncidentExtraction
    confidence: float
    duplicate_candidates: list[DuplicateLink] = Field(default_factory=list)
    request_id: str


class ScoreCaseResponse(BaseModel):
    case_id: str
    incident_id: str | None = None
    priority_score: float
    urgency: UrgencyKind
    rationale: PriorityRationale
    request_id: str


class RecommendationsResponse(BaseModel):
    case_id: str
    incident_id: str | None = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    unassigned_reason: str | None = None
    request_id: str


class AssignCaseRequest(BaseModel):
    team_id: str | None = None
    volunteer_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    resource_allocations: list[ResourceNeed] = Field(default_factory=list)


class AssignCaseResponse(BaseModel):
    assignment_id: str
    status: AssignmentStatus
    request_id: str


class MergeCaseRequest(BaseModel):
    merge_into_case_id: str


class MergeCaseResponse(BaseModel):
    status: str
    merged_case_id: str
    request_id: str


class UpdateLocationRequest(BaseModel):
    location_text: str
    lat: float | None = None
    lng: float | None = None
    location_confidence: LocationConfidence = LocationConfidence.APPROXIMATE


class UploadRegistrationRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int = 0
    linked_entity_type: str | None = "INCIDENT"
    linked_entity_id: str | None = None


class UploadRegistrationResponse(BaseModel):
    evidence_item: EvidenceItem
    upload_mode: str
    upload_url: str | None = None
    storage_path: str


class DispatchListResponse(BaseModel):
    items: list[AssignmentDecision]


class CaseDetailResponse(BaseModel):
    case: CaseRecord
    events: list[CaseEvent]
    duplicate_candidates: list[DuplicateLink]
    tokens: list[InfoToken] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    dispatches: list[AssignmentDecision] = Field(default_factory=list)


class CaseListResponse(BaseModel):
    items: list[CaseRecord]


class TeamsResponse(BaseModel):
    items: list[Team]


class VolunteersResponse(BaseModel):
    items: list[Volunteer]


class ResourcesResponse(BaseModel):
    items: list[ResourceInventory]


class IngestionJobsResponse(BaseModel):
    items: list[IngestionJob]


class DashboardSummary(BaseModel):
    total_cases: int
    open_cases: int
    critical_cases: int
    assigned_today: int
    pending_duplicates: int
    median_time_to_assign_minutes: int
    average_confidence: float
    mapped_cases: int = 0
    mapped_resources: int = 0
    mapped_teams: int = 0
    active_dispatches: int = 0


class EvalRunSummary(BaseModel):
    run_id: str
    created_at: datetime = Field(default_factory=utcnow)
    extraction_accuracy: float
    critical_mislabels: int
    duplicate_precision: float
    notes: str
