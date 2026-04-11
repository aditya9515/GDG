from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.domain import (
    AssignmentDecision,
    CaseDetailResponse,
    CaseEvent,
    CaseRecord,
    DashboardSummary,
    DuplicateLink,
    EvidenceItem,
    EvalRunSummary,
    IncidentExtraction,
    IngestionJob,
    InfoToken,
    PriorityRationale,
    Recommendation,
    ResourceInventory,
    Team,
    LocationConfidence,
    UploadRegistrationRequest,
    UploadRegistrationResponse,
    UserContext,
    UserProfile,
    Volunteer,
)


class Repository(ABC):
    @abstractmethod
    def create_case(self, raw_input: str, source_channel: str, actor: UserContext) -> CaseRecord: ...

    @abstractmethod
    def list_cases(self, status: str | None = None, urgency: str | None = None) -> list[CaseRecord]: ...

    @abstractmethod
    def get_case(self, case_id: str) -> CaseRecord: ...

    @abstractmethod
    def get_case_detail(self, case_id: str) -> CaseDetailResponse: ...

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
    def list_teams(self) -> list[Team]: ...

    @abstractmethod
    def list_resources(self) -> list[ResourceInventory]: ...

    @abstractmethod
    def save_team(self, team: Team) -> Team: ...

    @abstractmethod
    def save_resource(self, resource: ResourceInventory) -> ResourceInventory: ...

    @abstractmethod
    def save_recommendations(self, case_id: str, recommendations: list[Recommendation]) -> None: ...

    @abstractmethod
    def create_assignment(self, assignment: AssignmentDecision) -> AssignmentDecision: ...

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
    def get_user_profile(self, uid: str) -> UserProfile | None: ...
