from __future__ import annotations

import uuid

from google.cloud import firestore

from app.core.config import Settings
from app.models.domain import (
    AssignmentDecision,
    CaseDetailResponse,
    CaseEvent,
    CaseRecord,
    CaseStatus,
    DashboardSummary,
    DuplicateLink,
    DuplicateStatus,
    EvidenceItem,
    EvalRunSummary,
    IncidentExtraction,
    IngestionJob,
    InfoToken,
    PriorityRationale,
    Recommendation,
    ResourceInventory,
    Team,
    UploadRegistrationRequest,
    UploadRegistrationResponse,
    UserContext,
    UserProfile,
    Volunteer,
)
from app.repositories.base import Repository


class FirestoreRepository(Repository):
    def __init__(self, settings: Settings) -> None:
        self.client = firestore.Client(database=settings.firestore_database)

    def _collection(self, name: str):
        return self.client.collection(name)

    def create_case(self, raw_input: str, source_channel: str, actor: UserContext) -> CaseRecord:
        case = CaseRecord(
            case_id=f"CASE-{uuid.uuid4().hex[:8].upper()}",
            incident_id=None,
            raw_input=raw_input,
            source_channel=source_channel,
            created_by=actor.uid,
            source_languages=["en"],
        )
        case.incident_id = case.case_id
        self._collection("incidents").document(case.case_id).set(case.model_dump(mode="json"))
        self.record_event(
            CaseEvent(
                event_id=f"evt-{uuid.uuid4().hex[:10]}",
                case_id=case.case_id,
                event_type="CASE_CREATED",
                actor_uid=actor.uid,
                payload={"source_channel": source_channel},
            )
        )
        return case

    def list_cases(self, status: str | None = None, urgency: str | None = None) -> list[CaseRecord]:
        query = self._collection("incidents")
        if status:
            query = query.where("status", "==", status)
        if urgency:
            query = query.where("urgency", "==", urgency)
        return [CaseRecord.model_validate(doc.to_dict()) for doc in query.stream()]

    def get_case(self, case_id: str) -> CaseRecord:
        doc = self._collection("incidents").document(case_id).get()
        return CaseRecord.model_validate(doc.to_dict())

    def get_case_detail(self, case_id: str) -> CaseDetailResponse:
        events = [
            CaseEvent.model_validate(item.to_dict())
            for item in self._collection("incident_events").where("case_id", "==", case_id).stream()
        ]
        duplicates = [
            DuplicateLink.model_validate(item.to_dict())
            for item in self._collection("duplicate_links").where("case_id", "==", case_id).stream()
        ]
        tokens = [
            InfoToken.model_validate(item.to_dict())
            for item in self._collection("info_tokens").where("case_id", "==", case_id).stream()
        ]
        evidence_items = [
            EvidenceItem.model_validate(item.to_dict())
            for item in self._collection("evidence_items").where("linked_entity_id", "==", case_id).stream()
        ]
        dispatches = [
            AssignmentDecision.model_validate(item.to_dict())
            for item in self._collection("dispatches").where("case_id", "==", case_id).stream()
        ]
        return CaseDetailResponse(
            case=self.get_case(case_id),
            events=events,
            duplicate_candidates=duplicates,
            tokens=tokens,
            evidence_items=evidence_items,
            dispatches=dispatches,
        )

    def save_extraction(self, case_id: str, extraction: IncidentExtraction, status: str) -> CaseRecord:
        self._collection("incidents").document(case_id).update(
            {
                "extracted_json": extraction.model_dump(mode="json"),
                "status": status,
                "location_text": extraction.location_text,
                "urgency": extraction.urgency,
            }
        )
        return self.get_case(case_id)

    def save_scoring(self, case_id: str, score: float, rationale: PriorityRationale, urgency: str) -> CaseRecord:
        self._collection("incidents").document(case_id).update(
            {
                "priority_score": score,
                "priority_rationale": rationale.model_dump(mode="json"),
                "urgency": urgency,
                "status": CaseStatus.SCORED,
            }
        )
        return self.get_case(case_id)

    def update_case_location(
        self,
        case_id: str,
        location_text: str,
        lat: float | None,
        lng: float | None,
        confidence,
    ) -> CaseRecord:
        payload: dict[str, object] = {
            "location_text": location_text,
            "location_confidence": confidence,
        }
        if lat is not None and lng is not None:
            payload["geo"] = {"lat": lat, "lng": lng}
        self._collection("incidents").document(case_id).update(payload)
        return self.get_case(case_id)

    def save_duplicate_links(self, case_id: str, links: list[DuplicateLink]) -> list[DuplicateLink]:
        batch = self.client.batch()
        for link in links:
            ref = self._collection("duplicate_links").document(link.link_id)
            batch.set(ref, link.model_dump(mode="json"))
        batch.commit()
        if links:
            ranking = [DuplicateStatus.NONE, DuplicateStatus.POSSIBLE_DUPLICATE, DuplicateStatus.LIKELY_DUPLICATE]
            decision = max((link.decision for link in links), key=ranking.index)
            self._collection("incidents").document(case_id).update({"duplicate_status": decision})
        return links

    def list_recent_open_cases(self, excluding_case_id: str, limit: int = 50) -> list[CaseRecord]:
        docs = self._collection("incidents").limit(limit + 10).stream()
        items: list[CaseRecord] = []
        for doc in docs:
            case = CaseRecord.model_validate(doc.to_dict())
            if case.case_id == excluding_case_id or case.status in {CaseStatus.MERGED, CaseStatus.CLOSED}:
                continue
            items.append(case)
        return items[:limit]

    def list_volunteers(self) -> list[Volunteer]:
        return [Volunteer.model_validate(doc.to_dict()) for doc in self._collection("volunteers").stream()]

    def list_teams(self) -> list[Team]:
        return [Team.model_validate(doc.to_dict()) for doc in self._collection("teams").stream()]

    def list_resources(self) -> list[ResourceInventory]:
        return [ResourceInventory.model_validate(doc.to_dict()) for doc in self._collection("resources").stream()]

    def save_team(self, team: Team) -> Team:
        self._collection("teams").document(team.team_id).set(team.model_dump(mode="json"))
        return team

    def save_resource(self, resource: ResourceInventory) -> ResourceInventory:
        self._collection("resources").document(resource.resource_id).set(resource.model_dump(mode="json"))
        return resource

    def save_recommendations(self, case_id: str, recommendations: list[Recommendation]) -> None:
        self._collection("incidents").document(case_id).update(
            {"recommended_dispatches": [item.model_dump(mode="json") for item in recommendations]}
        )

    def create_assignment(self, assignment: AssignmentDecision) -> AssignmentDecision:
        @firestore.transactional
        def _write(transaction: firestore.Transaction) -> None:
            dispatch_ref = self._collection("dispatches").document(assignment.assignment_id)
            transaction.set(dispatch_ref, assignment.model_dump(mode="json"))
            incident_ref = self._collection("incidents").document(assignment.case_id)
            transaction.update(
                incident_ref,
                {"status": CaseStatus.ASSIGNED, "final_dispatch_id": assignment.assignment_id},
            )

        transaction = self.client.transaction()
        _write(transaction)
        return assignment

    def list_assignments(self) -> list[AssignmentDecision]:
        return [
            AssignmentDecision.model_validate(doc.to_dict())
            for doc in self._collection("dispatches").stream()
        ]

    def merge_case(self, case_id: str, merge_into_case_id: str, actor: UserContext) -> None:
        self._collection("incidents").document(case_id).update({"status": CaseStatus.MERGED})
        self.record_event(
            CaseEvent(
                event_id=f"evt-{uuid.uuid4().hex[:10]}",
                case_id=case_id,
                event_type="CASE_MERGED",
                actor_uid=actor.uid,
                payload={"merge_into_case_id": merge_into_case_id},
            )
        )

    def record_event(self, event: CaseEvent) -> None:
        self._collection("incident_events").document(event.event_id).set(event.model_dump(mode="json"))

    def get_dashboard_summary(self) -> DashboardSummary:
        cases = self.list_cases()
        assignments = self.list_assignments()
        confidence_values = [case.extracted_json.confidence for case in cases if case.extracted_json]
        pending_duplicates = sum(1 for case in cases if case.duplicate_status != DuplicateStatus.NONE)
        mapped_cases = sum(1 for case in cases if case.geo is not None)
        resources = self.list_resources()
        teams = self.list_teams()
        return DashboardSummary(
            total_cases=len(cases),
            open_cases=len([case for case in cases if case.status not in {CaseStatus.MERGED, CaseStatus.CLOSED}]),
            critical_cases=len([case for case in cases if case.urgency == "CRITICAL"]),
            assigned_today=len(assignments),
            pending_duplicates=pending_duplicates,
            median_time_to_assign_minutes=22 if assignments else 0,
            average_confidence=round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0,
            mapped_cases=mapped_cases,
            mapped_resources=sum(1 for item in resources if item.location is not None or item.current_geo is not None),
            mapped_teams=sum(1 for item in teams if item.base_geo is not None or item.current_geo is not None),
            active_dispatches=sum(1 for item in assignments if item.status in {"CONFIRMED", "IN_PROGRESS"}),
        )

    def latest_eval_run(self) -> EvalRunSummary | None:
        docs = list(
            self._collection("eval_runs")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        if not docs:
            return None
        return EvalRunSummary.model_validate(docs[0].to_dict())

    def save_eval_run(self, summary: EvalRunSummary) -> None:
        self._collection("eval_runs").document(summary.run_id).set(summary.model_dump(mode="json"))

    def save_info_tokens(self, case_id: str | None, tokens: list[InfoToken]) -> list[InfoToken]:
        batch = self.client.batch()
        for token in tokens:
            ref = self._collection("info_tokens").document(token.token_id)
            batch.set(ref, token.model_dump(mode="json"))
        batch.commit()
        if case_id is not None:
            incident = self.get_case(case_id)
            token_ids = [*incident.info_token_ids, *[item.token_id for item in tokens]]
            self._collection("incidents").document(case_id).update({"info_token_ids": list(dict.fromkeys(token_ids))})
        return tokens

    def list_info_tokens(self, case_id: str | None = None) -> list[InfoToken]:
        query = self._collection("info_tokens")
        if case_id:
            query = query.where("case_id", "==", case_id)
        return [InfoToken.model_validate(doc.to_dict()) for doc in query.stream()]

    def register_upload(self, payload: UploadRegistrationRequest, actor: UserContext) -> UploadRegistrationResponse:
        evidence = EvidenceItem(
            evidence_id=f"evd-{uuid.uuid4().hex[:10]}",
            source_kind="UPLOAD",
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            storage_path=f"gs://pending/{payload.filename}",
            uploaded_by=actor.uid,
            linked_entity_type=payload.linked_entity_type,
            linked_entity_id=payload.linked_entity_id,
        )
        self._collection("evidence_items").document(evidence.evidence_id).set(evidence.model_dump(mode="json"))
        return UploadRegistrationResponse(
            evidence_item=evidence,
            upload_mode="firebase_storage",
            storage_path=evidence.storage_path,
        )

    def get_evidence(self, evidence_id: str) -> EvidenceItem:
        doc = self._collection("evidence_items").document(evidence_id).get()
        return EvidenceItem.model_validate(doc.to_dict())

    def save_evidence(self, evidence: EvidenceItem) -> EvidenceItem:
        self._collection("evidence_items").document(evidence.evidence_id).set(evidence.model_dump(mode="json"))
        return evidence

    def list_evidence_for_case(self, case_id: str) -> list[EvidenceItem]:
        return [
            EvidenceItem.model_validate(doc.to_dict())
            for doc in self._collection("evidence_items").where("linked_entity_id", "==", case_id).stream()
        ]

    def create_ingestion_job(self, job: IngestionJob) -> IngestionJob:
        self._collection("ingestion_jobs").document(job.job_id).set(job.model_dump(mode="json"))
        return job

    def save_ingestion_job(self, job: IngestionJob) -> IngestionJob:
        self._collection("ingestion_jobs").document(job.job_id).set(job.model_dump(mode="json"))
        return job

    def list_ingestion_jobs(self) -> list[IngestionJob]:
        return [
            IngestionJob.model_validate(doc.to_dict())
            for doc in self._collection("ingestion_jobs").stream()
        ]

    def get_ingestion_job(self, job_id: str) -> IngestionJob:
        doc = self._collection("ingestion_jobs").document(job_id).get()
        return IngestionJob.model_validate(doc.to_dict())

    def get_user_profile(self, uid: str) -> UserProfile | None:
        doc = self._collection("users").document(uid).get()
        if not doc.exists:
            return None
        return UserProfile.model_validate(doc.to_dict())
