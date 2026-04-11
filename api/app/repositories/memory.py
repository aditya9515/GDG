from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.models.domain import (
    AssignmentDecision,
    AvailabilityStatus,
    CaseDetailResponse,
    CaseEvent,
    CaseRecord,
    CaseStatus,
    DashboardSummary,
    DuplicateLink,
    DuplicateStatus,
    EvidenceItem,
    EvalRunSummary,
    EvidenceStatus,
    GeoPoint,
    IncidentExtraction,
    IngestionJob,
    InfoToken,
    LocationConfidence,
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
from app.services.scoring import ScoringService


ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = ROOT / "seed"


def _load_json(name: str) -> list[dict]:
    path = SEED_DIR / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


class MemoryRepository(Repository):
    def __init__(self) -> None:
        self.cases: dict[str, CaseRecord] = {}
        self.events: dict[str, list[CaseEvent]] = {}
        self.duplicates: dict[str, list[DuplicateLink]] = {}
        self.recommendations: dict[str, list[Recommendation]] = {}
        self.assignments: dict[str, AssignmentDecision] = {}
        self.eval_runs: list[EvalRunSummary] = []
        self.info_tokens: dict[str, InfoToken] = {}
        self.evidence_items: dict[str, EvidenceItem] = {}
        self.ingestion_jobs: dict[str, IngestionJob] = {}
        self.users = {
            item["uid"]: UserProfile.model_validate(item)
            for item in _load_json("users.json")
        }
        self.volunteers = {
            item["volunteer_id"]: Volunteer.model_validate(item)
            for item in _load_json("volunteers.json")
        }
        self.resources = {
            item["resource_id"]: ResourceInventory.model_validate(item)
            for item in _load_json("resources.json")
        }
        self.teams = self._build_seed_teams()
        self.scoring_service = ScoringService()
        self._bootstrap_cases()

    def _build_seed_teams(self) -> dict[str, Team]:
        teams: dict[str, Team] = {}
        grouped_members: dict[str, list[Volunteer]] = {}
        team_names: dict[str, str] = {}
        team_capabilities: dict[str, set[str]] = {}

        for volunteer in self.volunteers.values():
            team_id = volunteer.team_id or f"TEAM-{volunteer.volunteer_id[-3:]}"
            volunteer.team_id = team_id
            grouped_members.setdefault(team_id, []).append(volunteer)
            team_names.setdefault(team_id, volunteer.display_name.split(" Team")[0].split(" Unit")[0])
            team_capabilities.setdefault(team_id, set()).update([*volunteer.role_tags, *volunteer.skills])

        for resource in self.resources.values():
            owning_team_id = resource.owning_team_id
            if owning_team_id is None:
                owning_team_id = self._guess_team_for_resource(resource.resource_type, grouped_members)
                resource.owning_team_id = owning_team_id
            team_capabilities.setdefault(owning_team_id, set()).add(resource.resource_type)

        for team_id, members in grouped_members.items():
            first = members[0]
            teams[team_id] = Team(
                team_id=team_id,
                display_name=team_names[team_id],
                capability_tags=sorted(team_capabilities.get(team_id, set())),
                member_ids=[member.volunteer_id for member in members],
                service_radius_km=45,
                base_label=first.home_base_label,
                base_geo=first.home_base,
                current_label=first.home_base_label,
                current_geo=first.current_geo or first.home_base,
                availability_status=AvailabilityStatus.AVAILABLE,
                active_dispatches=sum(member.active_assignments for member in members),
                reliability_score=round(
                    sum(member.reliability_score for member in members) / max(len(members), 1),
                    3,
                ),
            )
        return teams

    def _guess_team_for_resource(self, resource_type: str, grouped_members: dict[str, list[Volunteer]]) -> str:
        resource_upper = resource_type.upper()
        for team_id, members in grouped_members.items():
            combined = {skill.upper() for member in members for skill in [*member.skills, *member.role_tags]}
            if resource_upper in combined:
                return team_id
        return next(iter(grouped_members.keys()), "TEAM-GENERAL")

    def _bootstrap_cases(self) -> None:
        for item in _load_json("golden_cases.json"):
            extraction = IncidentExtraction.model_validate(item["expected"])
            rationale = self.scoring_service.score(extraction)
            case = CaseRecord(
                case_id=item["case_id"],
                incident_id=item["case_id"],
                raw_input=item["raw_input"],
                source_channel="SEEDED",
                status=CaseStatus.SCORED,
                extracted_json=extraction,
                priority_score=rationale.final_score,
                priority_rationale=rationale,
                urgency=rationale.final_urgency,
                location_text=extraction.location_text,
                location_confidence=(
                    LocationConfidence.APPROXIMATE
                    if extraction.data_quality.missing_location
                    else LocationConfidence.EXACT
                ),
                created_by="seed-loader",
                source_languages=["en"],
            )
            self.cases[case.case_id] = case
            self.events[case.case_id] = [
                CaseEvent(
                    event_id=f"evt-{case.case_id.lower()}-seed",
                    case_id=case.case_id,
                    event_type="SEEDED",
                    actor_uid="seed-loader",
                    payload={"source_channel": "SEEDED"},
                )
            ]
            self._seed_case_tokens(case)

        for item in _load_json("duplicate_pairs.json"):
            link = DuplicateLink.model_validate(item)
            self.duplicates.setdefault(link.case_id, []).append(link)
            if link.case_id in self.cases:
                self.cases[link.case_id].duplicate_status = link.decision

    def _seed_case_tokens(self, case: CaseRecord) -> None:
        extraction = case.extracted_json
        if extraction is None:
            return
        token = InfoToken(
            token_id=f"tok-{uuid.uuid4().hex[:10]}",
            token_type="NEED",
            source_kind="SEEDED_CASE",
            source_ref=case.case_id,
            summary=extraction.notes_for_dispatch,
            normalized_text=f"{extraction.category} {extraction.subcategory} {extraction.location_text}".strip(),
            redacted_text=extraction.notes_for_dispatch,
            language="en",
            confidence=extraction.confidence,
            case_id=case.case_id,
            linked_entity_type="INCIDENT",
            linked_entity_id=case.case_id,
            category=extraction.category,
            urgency_hint=extraction.urgency,
            location_text=extraction.location_text,
            geo=case.geo,
            location_confidence=case.location_confidence,
            quantity=extraction.people_affected,
            unit="people" if extraction.people_affected else None,
            time_window_hours=extraction.time_to_act_hours,
            metadata={"required_resources": [item.model_dump(mode="json") for item in extraction.required_resources]},
        )
        self.info_tokens[token.token_id] = token
        case.info_token_ids.append(token.token_id)

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
        self.cases[case.case_id] = case
        self.events[case.case_id] = []
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
        items = list(self.cases.values())
        if status:
            items = [item for item in items if item.status == status]
        if urgency:
            items = [item for item in items if item.urgency == urgency]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def get_case(self, case_id: str) -> CaseRecord:
        return self.cases[case_id]

    def get_case_detail(self, case_id: str) -> CaseDetailResponse:
        return CaseDetailResponse(
            case=self.cases[case_id],
            events=sorted(self.events.get(case_id, []), key=lambda item: item.timestamp),
            duplicate_candidates=self.duplicates.get(case_id, []),
            tokens=[token for token in self.info_tokens.values() if token.case_id == case_id],
            evidence_items=self.list_evidence_for_case(case_id),
            dispatches=[item for item in self.assignments.values() if item.case_id == case_id],
        )

    def save_extraction(self, case_id: str, extraction: IncidentExtraction, status: str) -> CaseRecord:
        case = self.cases[case_id]
        case.extracted_json = extraction
        case.status = status
        case.location_text = extraction.location_text
        case.urgency = extraction.urgency
        case.location_confidence = (
            LocationConfidence.APPROXIMATE
            if extraction.data_quality.missing_location
            else LocationConfidence.EXACT
        )
        case.source_languages = sorted(set(case.source_languages + ["en"]))
        self.cases[case_id] = case
        return case

    def save_scoring(self, case_id: str, score: float, rationale: PriorityRationale, urgency: str) -> CaseRecord:
        case = self.cases[case_id]
        case.priority_score = score
        case.priority_rationale = rationale
        case.urgency = urgency
        case.status = CaseStatus.SCORED
        self.cases[case_id] = case
        return case

    def update_case_location(
        self,
        case_id: str,
        location_text: str,
        lat: float | None,
        lng: float | None,
        confidence: LocationConfidence,
    ) -> CaseRecord:
        case = self.cases[case_id]
        case.location_text = location_text
        case.location_confidence = confidence
        if lat is not None and lng is not None:
            case.geo = GeoPoint(lat=lat, lng=lng)
        self.cases[case_id] = case
        return case

    def save_duplicate_links(self, case_id: str, links: list[DuplicateLink]) -> list[DuplicateLink]:
        self.duplicates[case_id] = links
        if links:
            ranking = [DuplicateStatus.NONE, DuplicateStatus.POSSIBLE_DUPLICATE, DuplicateStatus.LIKELY_DUPLICATE]
            self.cases[case_id].duplicate_status = max((link.decision for link in links), key=ranking.index)
        return links

    def list_recent_open_cases(self, excluding_case_id: str, limit: int = 50) -> list[CaseRecord]:
        items = [
            case
            for case in self.cases.values()
            if case.case_id != excluding_case_id and case.status not in {CaseStatus.MERGED, CaseStatus.CLOSED}
        ]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    def list_volunteers(self) -> list[Volunteer]:
        return list(self.volunteers.values())

    def list_teams(self) -> list[Team]:
        return list(self.teams.values())

    def list_resources(self) -> list[ResourceInventory]:
        return list(self.resources.values())

    def save_team(self, team: Team) -> Team:
        self.teams[team.team_id] = team
        return team

    def save_resource(self, resource: ResourceInventory) -> ResourceInventory:
        self.resources[resource.resource_id] = resource
        return resource

    def save_recommendations(self, case_id: str, recommendations: list[Recommendation]) -> None:
        self.recommendations[case_id] = recommendations
        case = self.cases[case_id]
        case.recommended_dispatches = recommendations
        self.cases[case_id] = case

    def create_assignment(self, assignment: AssignmentDecision) -> AssignmentDecision:
        self.assignments[assignment.assignment_id] = assignment
        case = self.cases[assignment.case_id]
        case.status = CaseStatus.ASSIGNED
        case.final_dispatch_id = assignment.assignment_id
        self.cases[assignment.case_id] = case

        if assignment.team_id and assignment.team_id in self.teams:
            team = self.teams[assignment.team_id]
            team.active_dispatches += 1
            team.availability_status = AvailabilityStatus.ON_MISSION
            self.teams[assignment.team_id] = team

        for volunteer_id in assignment.volunteer_ids:
            if volunteer_id not in self.volunteers:
                continue
            volunteer = self.volunteers[volunteer_id]
            volunteer.active_assignments += 1
            volunteer.availability_status = AvailabilityStatus.ON_MISSION
            self.volunteers[volunteer_id] = volunteer

        for resource_id in assignment.resource_ids:
            if resource_id not in self.resources:
                continue
            resource = self.resources[resource_id]
            resource.quantity_available = max(resource.quantity_available - 1, 0)
            self.resources[resource_id] = resource

        for allocation in assignment.resource_allocations:
            for resource in self.resources.values():
                if resource.resource_type != allocation.resource_type or resource.quantity_available <= 0:
                    continue
                decrement = allocation.quantity or 1
                resource.quantity_available = max(resource.quantity_available - decrement, 0)
                break
        return assignment

    def list_assignments(self) -> list[AssignmentDecision]:
        return sorted(self.assignments.values(), key=lambda item: item.confirmed_at, reverse=True)

    def merge_case(self, case_id: str, merge_into_case_id: str, actor: UserContext) -> None:
        case = self.cases[case_id]
        case.status = CaseStatus.MERGED
        self.cases[case_id] = case
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
        self.events.setdefault(event.case_id, []).append(event)

    def get_dashboard_summary(self) -> DashboardSummary:
        all_cases = list(self.cases.values())
        open_cases = [case for case in all_cases if case.status not in {CaseStatus.MERGED, CaseStatus.CLOSED}]
        critical_cases = [case for case in open_cases if case.urgency == "CRITICAL"]
        assigned = list(self.assignments.values())
        confidence_values = [case.extracted_json.confidence for case in all_cases if case.extracted_json is not None]
        pending_duplicates = sum(1 for case in open_cases if case.duplicate_status != DuplicateStatus.NONE)
        mapped_cases = sum(1 for case in all_cases if case.geo is not None)
        mapped_resources = sum(1 for item in self.resources.values() if item.location is not None or item.current_geo is not None)
        mapped_teams = sum(1 for item in self.teams.values() if item.base_geo is not None or item.current_geo is not None)
        active_dispatches = sum(1 for item in assigned if item.status in {"CONFIRMED", "IN_PROGRESS"})
        return DashboardSummary(
            total_cases=len(all_cases),
            open_cases=len(open_cases),
            critical_cases=len(critical_cases),
            assigned_today=len(assigned),
            pending_duplicates=pending_duplicates,
            median_time_to_assign_minutes=22 if assigned else 0,
            average_confidence=round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0,
            mapped_cases=mapped_cases,
            mapped_resources=mapped_resources,
            mapped_teams=mapped_teams,
            active_dispatches=active_dispatches,
        )

    def latest_eval_run(self) -> EvalRunSummary | None:
        return self.eval_runs[-1] if self.eval_runs else None

    def save_eval_run(self, summary: EvalRunSummary) -> None:
        self.eval_runs.append(summary)

    def save_info_tokens(self, case_id: str | None, tokens: list[InfoToken]) -> list[InfoToken]:
        case = self.cases[case_id] if case_id is not None and case_id in self.cases else None
        for token in tokens:
            if case_id is not None:
                token.case_id = case_id
                token.linked_entity_type = token.linked_entity_type or "INCIDENT"
                token.linked_entity_id = token.linked_entity_id or case_id
            self.info_tokens[token.token_id] = token
            if case is not None and token.token_id not in case.info_token_ids:
                case.info_token_ids.append(token.token_id)
        if case is not None:
            self.cases[case_id] = case
        return tokens

    def list_info_tokens(self, case_id: str | None = None) -> list[InfoToken]:
        items = list(self.info_tokens.values())
        if case_id:
            items = [item for item in items if item.case_id == case_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def register_upload(self, payload: UploadRegistrationRequest, actor: UserContext) -> UploadRegistrationResponse:
        evidence = EvidenceItem(
            evidence_id=f"evd-{uuid.uuid4().hex[:10]}",
            source_kind="UPLOAD",
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            storage_path=f"memory://uploads/{payload.filename}",
            uploaded_by=actor.uid,
            linked_entity_type=payload.linked_entity_type,
            linked_entity_id=payload.linked_entity_id,
        )
        self.evidence_items[evidence.evidence_id] = evidence
        if payload.linked_entity_id and payload.linked_entity_id in self.cases:
            case = self.cases[payload.linked_entity_id]
            case.evidence_ids.append(evidence.evidence_id)
            self.cases[payload.linked_entity_id] = case
        return UploadRegistrationResponse(
            evidence_item=evidence,
            upload_mode="backend_multipart",
            storage_path=evidence.storage_path,
        )

    def get_evidence(self, evidence_id: str) -> EvidenceItem:
        return self.evidence_items[evidence_id]

    def save_evidence(self, evidence: EvidenceItem) -> EvidenceItem:
        self.evidence_items[evidence.evidence_id] = evidence
        if evidence.incident_id and evidence.incident_id in self.cases:
            case = self.cases[evidence.incident_id]
            if evidence.evidence_id not in case.evidence_ids:
                case.evidence_ids.append(evidence.evidence_id)
            self.cases[evidence.incident_id] = case
        return evidence

    def list_evidence_for_case(self, case_id: str) -> list[EvidenceItem]:
        return [
            item
            for item in self.evidence_items.values()
            if item.incident_id == case_id or item.linked_entity_id == case_id
        ]

    def create_ingestion_job(self, job: IngestionJob) -> IngestionJob:
        self.ingestion_jobs[job.job_id] = job
        return job

    def save_ingestion_job(self, job: IngestionJob) -> IngestionJob:
        self.ingestion_jobs[job.job_id] = job
        return job

    def list_ingestion_jobs(self) -> list[IngestionJob]:
        return sorted(self.ingestion_jobs.values(), key=lambda item: item.created_at, reverse=True)

    def get_ingestion_job(self, job_id: str) -> IngestionJob:
        return self.ingestion_jobs[job_id]

    def get_user_profile(self, uid: str) -> UserProfile | None:
        return self.users.get(uid)
