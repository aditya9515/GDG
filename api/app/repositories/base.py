from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.domain import (
    AssignmentDecision,
    AuditEvent,
    CaseDetailResponse,
    CaseEvent,
    CaseRecord,
    DashboardSummary,
    DuplicateLink,
    EvidenceItem,
    EvalRunSummary,
    GeocodeCacheEntry,
    GraphRun,
    IncidentExtraction,
    IngestionJob,
    InfoToken,
    PriorityRationale,
    Recommendation,
    ResourceInventory,
    Team,
    LocationConfidence,
    MembershipStatus,
    Organization,
    OrgMembership,
    OrgRole,
    UploadRegistrationRequest,
    UploadRegistrationResponse,
    UserContext,
    UserProfile,
    VectorRecord,
    Volunteer,
)


class Repository(ABC):
    @abstractmethod
    def create_case(self, raw_input: str, source_channel: str, actor: UserContext, source_hash: str | None = None) -> CaseRecord: ...

    @abstractmethod
    def list_cases(self, status: str | None = None, urgency: str | None = None) -> list[CaseRecord]: ...

    @abstractmethod
    def get_case(self, case_id: str) -> CaseRecord: ...

    @abstractmethod
    def get_case_detail(self, case_id: str) -> CaseDetailResponse: ...

    @abstractmethod
    def delete_case(self, case_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def save_extraction(self, case_id: str, extraction: IncidentExtraction, status: str) -> CaseRecord: ...

    @abstractmethod
    def save_scoring(self, case_id: str, score: float, rationale: PriorityRationale, urgency: str) -> CaseRecord: ...

    @abstractmethod
    def update_case_location(
        self,
        case_id: str,
        location_text: str,
        lat: float | None,
        lng: float | None,
        confidence: LocationConfidence,
    ) -> CaseRecord: ...

    @abstractmethod
    def save_duplicate_links(self, case_id: str, links: list[DuplicateLink]) -> list[DuplicateLink]: ...

    @abstractmethod
    def list_recent_open_cases(self, excluding_case_id: str, limit: int = 50) -> list[CaseRecord]: ...

    @abstractmethod
    def list_volunteers(self) -> list[Volunteer]: ...

    @abstractmethod
    def save_volunteer(self, volunteer: Volunteer) -> Volunteer: ...

    @abstractmethod
    def delete_volunteer(self, volunteer_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def list_teams(self) -> list[Team]: ...

    @abstractmethod
    def list_resources(self) -> list[ResourceInventory]: ...

    @abstractmethod
    def save_team(self, team: Team) -> Team: ...

    @abstractmethod
    def delete_team(self, team_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def save_resource(self, resource: ResourceInventory) -> ResourceInventory: ...

    @abstractmethod
    def delete_resource(self, resource_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def save_recommendations(self, case_id: str, recommendations: list[Recommendation]) -> None: ...

    @abstractmethod
    def create_assignment(self, assignment: AssignmentDecision) -> AssignmentDecision: ...

    @abstractmethod
    def delete_assignment(self, assignment_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def list_assignments(self) -> list[AssignmentDecision]: ...

    @abstractmethod
    def merge_case(self, case_id: str, merge_into_case_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def record_event(self, event: CaseEvent) -> None: ...

    @abstractmethod
    def get_dashboard_summary(self) -> DashboardSummary: ...

    @abstractmethod
    def latest_eval_run(self) -> EvalRunSummary | None: ...

    @abstractmethod
    def save_eval_run(self, summary: EvalRunSummary) -> None: ...

    @abstractmethod
    def save_info_tokens(self, case_id: str | None, tokens: list[InfoToken]) -> list[InfoToken]: ...

    @abstractmethod
    def list_info_tokens(self, case_id: str | None = None) -> list[InfoToken]: ...

    @abstractmethod
    def register_upload(self, payload: UploadRegistrationRequest, actor: UserContext) -> UploadRegistrationResponse: ...

    @abstractmethod
    def get_evidence(self, evidence_id: str) -> EvidenceItem: ...

    @abstractmethod
    def save_evidence(self, evidence: EvidenceItem) -> EvidenceItem: ...

    @abstractmethod
    def list_evidence_for_case(self, case_id: str) -> list[EvidenceItem]: ...

    @abstractmethod
    def create_ingestion_job(self, job: IngestionJob) -> IngestionJob: ...

    @abstractmethod
    def save_ingestion_job(self, job: IngestionJob) -> IngestionJob: ...

    @abstractmethod
    def list_ingestion_jobs(self) -> list[IngestionJob]: ...

    @abstractmethod
    def get_ingestion_job(self, job_id: str) -> IngestionJob: ...

    @abstractmethod
    def delete_ingestion_job(self, job_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def get_user_profile(self, uid: str) -> UserProfile | None: ...

    @abstractmethod
    def get_user_profile_by_email(self, email: str) -> UserProfile | None: ...

    @abstractmethod
    def save_user_profile(self, profile: UserProfile) -> UserProfile: ...

    @abstractmethod
    def create_organization(self, name: str, actor: UserContext) -> tuple[Organization, OrgMembership]: ...

    @abstractmethod
    def list_organizations_for_user(self, uid: str, email: str | None = None) -> tuple[list[Organization], list[OrgMembership]]: ...

    @abstractmethod
    def get_organization(self, org_id: str) -> Organization | None: ...

    @abstractmethod
    def list_org_members(self, org_id: str) -> list[OrgMembership]: ...

    @abstractmethod
    def get_org_membership(self, org_id: str, uid: str | None = None, email: str | None = None) -> OrgMembership | None: ...

    @abstractmethod
    def update_org_member(self, org_id: str, membership_id: str, role: OrgRole | None, status: MembershipStatus | None, actor: UserContext) -> OrgMembership: ...

    @abstractmethod
    def bind_membership_uid(self, membership: OrgMembership, uid: str) -> OrgMembership: ...

    @abstractmethod
    def record_audit_event(self, event: AuditEvent) -> None: ...

    @abstractmethod
    def reset_organization_data(self, org_id: str, actor: UserContext) -> dict[str, int]: ...

    @abstractmethod
    def save_graph_run(self, run: GraphRun) -> GraphRun: ...

    @abstractmethod
    def get_graph_run(self, run_id: str) -> GraphRun: ...

    @abstractmethod
    def delete_graph_run(self, run_id: str, actor: UserContext) -> None: ...

    @abstractmethod
    def save_vector_records(self, records: list[VectorRecord]) -> list[VectorRecord]: ...

    @abstractmethod
    def search_vector_records(self, org_id: str, query_embedding: list[float], limit: int = 8) -> list[VectorRecord]: ...

    @abstractmethod
    def get_geocode_cache(self, cache_key: str) -> GeocodeCacheEntry | None: ...

    @abstractmethod
    def save_geocode_cache(self, entry: GeocodeCacheEntry) -> GeocodeCacheEntry: ...
