from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

from app.models.domain import (
    AssignmentDecision,
    AuditEvent,
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
    GeocodeCacheEntry,
    GeoPoint,
    GraphRun,
    IncidentExtraction,
    IngestionJob,
    InfoToken,
    LocationConfidence,
    MembershipStatus,
    OrgInvite,
    Organization,
    OrgMembership,
    OrgRole,
    OrgStatus,
    PriorityRationale,
    Recommendation,
    ResourceInventory,
    Team,
    UploadRegistrationRequest,
    UploadRegistrationResponse,
    UserContext,
    UserProfile,
    VectorRecord,
    Volunteer,
    utcnow,
)
from app.repositories.base import Repository
from app.services.scoring import ScoringService


ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = ROOT / "seed"
DEFAULT_ORG_ID = "org-demo-relief"


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
        self.geocode_cache: dict[str, GeocodeCacheEntry] = {}
        self.organizations = {
            item["org_id"]: Organization.model_validate(item)
            for item in _load_json("organizations.json")
        }
        self.memberships = {
            item["membership_id"]: OrgMembership.model_validate(item)
            for item in _load_json("org_memberships.json")
        }
        self.invites = {
            item["invite_id"]: OrgInvite.model_validate(item)
            for item in _load_json("org_invites.json")
        }
        self.audit_events: dict[str, AuditEvent] = {}
        self.graph_runs: dict[str, GraphRun] = {}
        self.vector_records: dict[str, VectorRecord] = {}
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
        self._ensure_default_org()
        self.teams = self._build_seed_teams()
        self.scoring_service = ScoringService()
        self._bootstrap_cases()

    def _ensure_default_org(self) -> None:
        if not self.organizations:
            self.organizations[DEFAULT_ORG_ID] = Organization(
                org_id=DEFAULT_ORG_ID,
                name="Demo Relief NGO",
                host_uid="demo-coordinator",
                host_email="demo@reliefops.local",
                status=OrgStatus.ACTIVE,
            )
        for uid, profile in self.users.items():
            if not profile.default_org_id:
                profile.default_org_id = DEFAULT_ORG_ID
            if DEFAULT_ORG_ID not in profile.org_ids:
                profile.org_ids.append(DEFAULT_ORG_ID)
            if DEFAULT_ORG_ID not in profile.role_by_org:
                role = OrgRole.HOST if uid == "demo-coordinator" else OrgRole(str(profile.role))
                profile.role_by_org[DEFAULT_ORG_ID] = role
            self.users[uid] = profile
            membership_id = f"{DEFAULT_ORG_ID}-{uid}"
            if membership_id not in self.memberships:
                self.memberships[membership_id] = OrgMembership(
                    membership_id=membership_id,
                    org_id=DEFAULT_ORG_ID,
                    uid=uid,
                    email=profile.email or f"{uid}@reliefops.local",
                    role=profile.role_by_org[DEFAULT_ORG_ID],
                    status=MembershipStatus.ACTIVE,
                    invited_by="seed-loader",
                )
        for volunteer in self.volunteers.values():
            volunteer.org_id = volunteer.org_id or DEFAULT_ORG_ID
        for resource in self.resources.values():
            resource.org_id = resource.org_id or DEFAULT_ORG_ID

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
                org_id=first.org_id,
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
                org_id=DEFAULT_ORG_ID,
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
            org_id=case.org_id,
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

    def _require_org_scope(self, org_id: str | None, actor: UserContext) -> None:
        if org_id != actor.active_org_id:
            raise PermissionError("Record belongs to another organization.")

    def _delete_vectors_for(self, record_id: str, token_ids: set[str] | None = None) -> None:
        token_ids = token_ids or set()
        for vector_id, vector in list(self.vector_records.items()):
            if vector.record_id == record_id or (vector.token_id and vector.token_id in token_ids):
                self.vector_records.pop(vector_id, None)

    def _record_delete_audit(self, deleted_type: str, deleted_id: str, org_id: str | None, actor: UserContext) -> None:
        self.record_audit_event(
            AuditEvent(
                audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                org_id=org_id,
                actor_uid=actor.uid,
                action=f"{deleted_type.upper()}_DELETED",
                object_ref=deleted_id,
                payload={"deleted_type": deleted_type},
            )
        )

    def create_case(self, raw_input: str, source_channel: str, actor: UserContext, source_hash: str | None = None) -> CaseRecord:
        case = CaseRecord(
            case_id=f"CASE-{uuid.uuid4().hex[:8].upper()}",
            org_id=actor.active_org_id or DEFAULT_ORG_ID,
            incident_id=None,
            raw_input=raw_input,
            source_channel=source_channel,
            created_by=actor.uid,
            source_languages=["en"],
            source_hash=source_hash,
        )
        case.incident_id = case.case_id
        self.cases[case.case_id] = case
        self.events[case.case_id] = []
        self.record_event(
            CaseEvent(
                event_id=f"evt-{uuid.uuid4().hex[:10]}",
                org_id=case.org_id,
                case_id=case.case_id,
                event_type="CASE_CREATED",
                actor_uid=actor.uid,
                payload={"source_channel": source_channel},
            )
        )
        return case

    def list_cases(self, status: str | None = None, urgency: str | None = None) -> list[CaseRecord]:
        items = list(self.cases.values())
        # Operational lists are org-scoped when the actor has selected an org.
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

    def delete_case(self, case_id: str, actor: UserContext) -> None:
        case = self.cases[case_id]
        self._require_org_scope(case.org_id, actor)
        for assignment_id, assignment in list(self.assignments.items()):
            if assignment.case_id == case_id:
                self.assignments.pop(assignment_id, None)
        token_ids = {
            token_id
            for token_id, token in self.info_tokens.items()
            if token.case_id == case_id or token.linked_entity_id == case_id
        }
        for token_id in token_ids:
            self.info_tokens.pop(token_id, None)
        for evidence_id, evidence in list(self.evidence_items.items()):
            if evidence.incident_id == case_id or evidence.linked_entity_id == case_id:
                self.evidence_items.pop(evidence_id, None)
        self.events.pop(case_id, None)
        self.duplicates.pop(case_id, None)
        for linked_case_id, links in list(self.duplicates.items()):
            kept = [link for link in links if link.other_case_id != case_id]
            if kept:
                self.duplicates[linked_case_id] = kept
            else:
                self.duplicates.pop(linked_case_id, None)
                if linked_case_id in self.cases:
                    self.cases[linked_case_id].duplicate_status = DuplicateStatus.NONE
        self.recommendations.pop(case_id, None)
        self._delete_vectors_for(case_id, token_ids)
        self.cases.pop(case_id, None)
        self._record_delete_audit("incident", case_id, case.org_id, actor)

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

    def save_volunteer(self, volunteer: Volunteer) -> Volunteer:
        volunteer.updated_at = utcnow()
        self.volunteers[volunteer.volunteer_id] = volunteer
        return volunteer

    def delete_volunteer(self, volunteer_id: str, actor: UserContext) -> None:
        volunteer = self.volunteers[volunteer_id]
        self._require_org_scope(volunteer.org_id, actor)
        for team in self.teams.values():
            team.member_ids = [item for item in team.member_ids if item != volunteer_id]
        for assignment in self.assignments.values():
            assignment.volunteer_ids = [item for item in assignment.volunteer_ids if item != volunteer_id]
        self.volunteers.pop(volunteer_id, None)
        self._record_delete_audit("volunteer", volunteer_id, volunteer.org_id, actor)

    def list_teams(self) -> list[Team]:
        return list(self.teams.values())

    def list_resources(self) -> list[ResourceInventory]:
        return list(self.resources.values())

    def save_team(self, team: Team) -> Team:
        team.updated_at = utcnow()
        self.teams[team.team_id] = team
        return team

    def delete_team(self, team_id: str, actor: UserContext) -> None:
        team = self.teams[team_id]
        self._require_org_scope(team.org_id, actor)
        for assignment in self.assignments.values():
            if assignment.team_id == team_id:
                assignment.team_id = None
        token_ids = {
            token_id
            for token_id, token in self.info_tokens.items()
            if token.linked_entity_type == "TEAM" and token.linked_entity_id == team_id
        }
        for token_id in token_ids:
            self.info_tokens.pop(token_id, None)
        self._delete_vectors_for(team_id, token_ids)
        self.teams.pop(team_id, None)
        self._record_delete_audit("team", team_id, team.org_id, actor)

    def save_resource(self, resource: ResourceInventory) -> ResourceInventory:
        resource.updated_at = utcnow()
        self.resources[resource.resource_id] = resource
        return resource

    def delete_resource(self, resource_id: str, actor: UserContext) -> None:
        resource = self.resources[resource_id]
        self._require_org_scope(resource.org_id, actor)
        for assignment in self.assignments.values():
            assignment.resource_ids = [item for item in assignment.resource_ids if item != resource_id]
        token_ids = {
            token_id
            for token_id, token in self.info_tokens.items()
            if token.linked_entity_type == "RESOURCE" and token.linked_entity_id == resource_id
        }
        for token_id in token_ids:
            self.info_tokens.pop(token_id, None)
        self._delete_vectors_for(resource_id, token_ids)
        self.resources.pop(resource_id, None)
        self._record_delete_audit("resource", resource_id, resource.org_id, actor)

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

    def delete_assignment(self, assignment_id: str, actor: UserContext) -> None:
        assignment = self.assignments[assignment_id]
        self._require_org_scope(assignment.org_id, actor)
        if assignment.case_id in self.cases:
            case = self.cases[assignment.case_id]
            if case.final_dispatch_id == assignment_id:
                case.final_dispatch_id = None
                case.status = CaseStatus.SCORED if case.priority_score is not None else CaseStatus.NEW
                self.cases[case.case_id] = case
        if assignment.team_id and assignment.team_id in self.teams:
            team = self.teams[assignment.team_id]
            team.active_dispatches = max(team.active_dispatches - 1, 0)
            if team.active_dispatches == 0:
                team.availability_status = AvailabilityStatus.AVAILABLE
            self.teams[team.team_id] = team
        for volunteer_id in assignment.volunteer_ids:
            if volunteer_id not in self.volunteers:
                continue
            volunteer = self.volunteers[volunteer_id]
            volunteer.active_assignments = max(volunteer.active_assignments - 1, 0)
            if volunteer.active_assignments == 0:
                volunteer.availability_status = AvailabilityStatus.AVAILABLE
            self.volunteers[volunteer_id] = volunteer
        for resource_id in assignment.resource_ids:
            if resource_id in self.resources:
                self.resources[resource_id].quantity_available += 1
        for allocation in assignment.resource_allocations:
            for resource in self.resources.values():
                if resource.org_id != actor.active_org_id or resource.resource_type != allocation.resource_type:
                    continue
                resource.quantity_available += allocation.quantity or 1
                break
        self.assignments.pop(assignment_id, None)
        self._record_delete_audit("dispatch", assignment_id, assignment.org_id, actor)

    def merge_case(self, case_id: str, merge_into_case_id: str, actor: UserContext) -> None:
        case = self.cases[case_id]
        case.status = CaseStatus.MERGED
        self.cases[case_id] = case
        self.record_event(
            CaseEvent(
                event_id=f"evt-{uuid.uuid4().hex[:10]}",
                org_id=case.org_id,
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
        evidence_id = f"evd-{uuid.uuid4().hex[:10]}"
        evidence = EvidenceItem(
            evidence_id=evidence_id,
            source_kind="UPLOAD",
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            storage_path=f"memory://evidence/{actor.uid}/{evidence_id}/{payload.filename}",
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

    def delete_ingestion_job(self, job_id: str, actor: UserContext) -> None:
        job = self.ingestion_jobs[job_id]
        self._require_org_scope(job.org_id, actor)
        for case_id in list(job.produced_case_ids):
            if case_id in self.cases:
                self.delete_case(case_id, actor)
        produced_tokens = [self.info_tokens[token_id] for token_id in job.produced_token_ids if token_id in self.info_tokens]
        for token in produced_tokens:
            if token.linked_entity_type == "TEAM" and token.linked_entity_id in self.teams:
                self.delete_team(token.linked_entity_id, actor)
            elif token.linked_entity_type == "RESOURCE" and token.linked_entity_id in self.resources:
                self.delete_resource(token.linked_entity_id, actor)
        self.ingestion_jobs.pop(job_id, None)
        for token_id in list(job.produced_token_ids):
            self.info_tokens.pop(token_id, None)
        for vector_id, vector in list(self.vector_records.items()):
            if job_id in vector.source_refs:
                self.vector_records.pop(vector_id, None)
        self._record_delete_audit("ingestion_job", job_id, job.org_id, actor)

    def get_user_profile(self, uid: str) -> UserProfile | None:
        return self.users.get(uid)

    def get_user_profile_by_email(self, email: str) -> UserProfile | None:
        normalized = email.strip().lower()
        return next(
            (
                profile
                for profile in self.users.values()
                if profile.email and profile.email.strip().lower() == normalized
            ),
            None,
        )

    def save_user_profile(self, profile: UserProfile) -> UserProfile:
        self.users[profile.uid] = profile
        return profile

    def create_organization(self, name: str, actor: UserContext) -> tuple[Organization, OrgMembership]:
        org_id = f"org-{uuid.uuid4().hex[:10]}"
        organization = Organization(
            org_id=org_id,
            name=name.strip(),
            host_uid=actor.uid,
            host_email=actor.email,
        )
        membership = OrgMembership(
            membership_id=f"{org_id}-{actor.uid}",
            org_id=org_id,
            uid=actor.uid,
            email=actor.email or f"{actor.uid}@reliefops.local",
            role=OrgRole.HOST,
            status=MembershipStatus.ACTIVE,
            invited_by=actor.uid,
        )
        self.organizations[org_id] = organization
        self.memberships[membership.membership_id] = membership
        profile = self.users.get(actor.uid) or UserProfile(
            uid=actor.uid,
            email=actor.email,
            role=OrgRole.HOST,
            enabled=True,
        )
        profile.default_org_id = profile.default_org_id or org_id
        profile.org_ids = list(dict.fromkeys([*profile.org_ids, org_id]))
        profile.role_by_org[org_id] = OrgRole.HOST
        profile.role = OrgRole.HOST
        self.users[profile.uid] = profile
        self.record_audit_event(
            AuditEvent(
                audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                org_id=org_id,
                actor_uid=actor.uid,
                action="ORG_CREATED",
                object_ref=org_id,
                payload={"name": name},
            )
        )
        return organization, membership

    def list_organizations_for_user(self, uid: str, email: str | None = None) -> tuple[list[Organization], list[OrgMembership]]:
        normalized_email = email.strip().lower() if email else None
        memberships = [
            membership
            for membership in self.memberships.values()
            if membership.status == MembershipStatus.ACTIVE
            and (membership.uid == uid or (normalized_email and membership.email.strip().lower() == normalized_email))
        ]
        organizations = [self.organizations[item.org_id] for item in memberships if item.org_id in self.organizations]
        return organizations, memberships

    def get_organization(self, org_id: str) -> Organization | None:
        return self.organizations.get(org_id)

    def list_org_members(self, org_id: str) -> list[OrgMembership]:
        return [item for item in self.memberships.values() if item.org_id == org_id and item.status != MembershipStatus.REMOVED]

    def list_org_invites(self, org_id: str) -> list[OrgInvite]:
        return [item for item in self.invites.values() if item.org_id == org_id and item.status == MembershipStatus.INVITED]

    def get_org_membership(self, org_id: str, uid: str | None = None, email: str | None = None) -> OrgMembership | None:
        normalized_email = email.strip().lower() if email else None
        for membership in self.memberships.values():
            if membership.org_id != org_id or membership.status != MembershipStatus.ACTIVE:
                continue
            if uid and membership.uid == uid:
                return membership
            if normalized_email and membership.email.strip().lower() == normalized_email:
                return membership
        return None

    def create_org_invite(self, org_id: str, email: str, role: OrgRole, actor: UserContext) -> OrgInvite:
        normalized = email.strip().lower()
        existing = self.get_org_membership(org_id, email=normalized)
        if existing is None:
            membership = OrgMembership(
                membership_id=f"{org_id}-invite-{uuid.uuid4().hex[:8]}",
                org_id=org_id,
                email=normalized,
                role=role,
                status=MembershipStatus.ACTIVE,
                invited_by=actor.uid,
            )
            self.memberships[membership.membership_id] = membership
        invite = OrgInvite(
            invite_id=f"inv-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            email=normalized,
            role=role,
            invited_by=actor.uid,
        )
        self.invites[invite.invite_id] = invite
        self.record_audit_event(
            AuditEvent(
                audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                org_id=org_id,
                actor_uid=actor.uid,
                action="MEMBER_INVITED",
                object_ref=normalized,
                payload={"role": role},
            )
        )
        return invite

    def update_org_member(
        self,
        org_id: str,
        membership_id: str,
        role: OrgRole | None,
        status: MembershipStatus | None,
        actor: UserContext,
    ) -> OrgMembership:
        membership = self.memberships[membership_id]
        if membership.org_id != org_id:
            raise KeyError(membership_id)
        if role is not None:
            membership.role = role
        if status is not None:
            membership.status = status
            if status in {MembershipStatus.DISABLED, MembershipStatus.REMOVED}:
                membership.disabled_at = utcnow()
        self.memberships[membership_id] = membership
        self.record_audit_event(
            AuditEvent(
                audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                org_id=org_id,
                actor_uid=actor.uid,
                action="MEMBER_UPDATED",
                object_ref=membership_id,
                payload={"role": role, "status": status},
            )
        )
        return membership

    def bind_membership_uid(self, membership: OrgMembership, uid: str) -> OrgMembership:
        membership.uid = uid
        membership.status = MembershipStatus.ACTIVE
        membership.joined_at = membership.joined_at or utcnow()
        self.memberships[membership.membership_id] = membership
        return membership

    def record_audit_event(self, event: AuditEvent) -> None:
        self.audit_events[event.audit_id] = event

    def reset_organization_data(self, org_id: str, actor: UserContext) -> dict[str, int]:
        if actor.active_org_id != org_id:
            raise PermissionError("Can only reset the active organization.")

        counts = {
            "incidents": 0,
            "incident_events": 0,
            "duplicate_links": 0,
            "dispatches": 0,
            "teams": 0,
            "volunteers": 0,
            "resources": 0,
            "info_tokens": 0,
            "vector_records": 0,
            "evidence_items": 0,
            "ingestion_jobs": 0,
            "agent_runs": 0,
            "audit_events": 0,
        }

        case_ids = {case_id for case_id, case in self.cases.items() if case.org_id == org_id}
        team_ids = {team_id for team_id, team in self.teams.items() if team.org_id == org_id}
        volunteer_ids = {volunteer_id for volunteer_id, volunteer in self.volunteers.items() if volunteer.org_id == org_id}
        resource_ids = {resource_id for resource_id, resource in self.resources.items() if resource.org_id == org_id}

        for case_id in list(case_ids):
            self.cases.pop(case_id, None)
            counts["incidents"] += 1
            counts["incident_events"] += len(self.events.pop(case_id, []))
            counts["duplicate_links"] += len(self.duplicates.pop(case_id, []))
            self.recommendations.pop(case_id, None)

        for linked_case_id, links in list(self.duplicates.items()):
            kept = [link for link in links if link.other_case_id not in case_ids]
            counts["duplicate_links"] += len(links) - len(kept)
            if kept:
                self.duplicates[linked_case_id] = kept
            else:
                self.duplicates.pop(linked_case_id, None)

        for assignment_id, assignment in list(self.assignments.items()):
            if assignment.org_id == org_id or assignment.case_id in case_ids:
                self.assignments.pop(assignment_id, None)
                counts["dispatches"] += 1

        for team_id in list(team_ids):
            self.teams.pop(team_id, None)
            counts["teams"] += 1
        for volunteer_id in list(volunteer_ids):
            self.volunteers.pop(volunteer_id, None)
            counts["volunteers"] += 1
        for resource_id in list(resource_ids):
            self.resources.pop(resource_id, None)
            counts["resources"] += 1

        removed_record_ids = case_ids | team_ids | volunteer_ids | resource_ids
        token_ids: set[str] = set()
        for token_id, token in list(self.info_tokens.items()):
            if (
                token.org_id == org_id
                or token.case_id in case_ids
                or (token.linked_entity_id and token.linked_entity_id in removed_record_ids)
            ):
                token_ids.add(token_id)
                self.info_tokens.pop(token_id, None)
                counts["info_tokens"] += 1

        for evidence_id, evidence in list(self.evidence_items.items()):
            if (
                evidence.org_id == org_id
                or evidence.incident_id in case_ids
                or (evidence.linked_entity_id and evidence.linked_entity_id in removed_record_ids)
            ):
                self.evidence_items.pop(evidence_id, None)
                counts["evidence_items"] += 1

        for job_id, job in list(self.ingestion_jobs.items()):
            if job.org_id == org_id:
                self.ingestion_jobs.pop(job_id, None)
                counts["ingestion_jobs"] += 1

        for run_id, run in list(self.graph_runs.items()):
            if run.org_id == org_id:
                self.graph_runs.pop(run_id, None)
                counts["agent_runs"] += 1

        for vector_id, vector in list(self.vector_records.items()):
            if (
                vector.org_id == org_id
                or vector.record_id in removed_record_ids
                or (vector.token_id and vector.token_id in token_ids)
            ):
                self.vector_records.pop(vector_id, None)
                counts["vector_records"] += 1

        for audit_id, audit in list(self.audit_events.items()):
            if audit.org_id == org_id:
                self.audit_events.pop(audit_id, None)
                counts["audit_events"] += 1

        self.record_audit_event(
            AuditEvent(
                audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                org_id=org_id,
                actor_uid=actor.uid,
                action="ORG_DATA_RESET",
                object_ref=org_id,
                payload={"deleted_counts": counts},
            )
        )
        return counts

    def save_graph_run(self, run: GraphRun) -> GraphRun:
        run.updated_at = utcnow()
        self.graph_runs[run.run_id] = run
        return run

    def get_graph_run(self, run_id: str) -> GraphRun:
        return self.graph_runs[run_id]

    def delete_graph_run(self, run_id: str, actor: UserContext) -> None:
        run = self.graph_runs[run_id]
        self._require_org_scope(run.org_id, actor)
        self.graph_runs.pop(run_id, None)
        self._record_delete_audit("graph_run", run_id, run.org_id, actor)

    def save_vector_records(self, records: list[VectorRecord]) -> list[VectorRecord]:
        for record in records:
            self.vector_records[record.vector_id] = record
        return records

    def search_vector_records(self, org_id: str, query_embedding: list[float], limit: int = 8) -> list[VectorRecord]:
        active = [
            item
            for item in self.vector_records.values()
            if item.org_id == org_id and item.deleted_at is None and item.status == "ACTIVE"
        ]
        if not query_embedding:
            return active[:limit]
        scored = sorted(
            active,
            key=lambda item: self._cosine(query_embedding, item.embedding),
            reverse=True,
        )
        return scored[:limit]

    def _cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def get_geocode_cache(self, cache_key: str) -> GeocodeCacheEntry | None:
        return self.geocode_cache.get(cache_key)

    def save_geocode_cache(self, entry: GeocodeCacheEntry) -> GeocodeCacheEntry:
        self.geocode_cache[entry.cache_key] = entry
        return entry
