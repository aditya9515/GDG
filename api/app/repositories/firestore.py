from __future__ import annotations

import uuid
from datetime import UTC, datetime
import math

from google.cloud import firestore

from app.core.config import Settings
from app.models.domain import (
    AvailabilityStatus,
    AssignmentDecision,
    AuditEvent,
    CaseDetailResponse,
    CaseEvent,
    CaseRecord,
    CaseStatus,
    DashboardSummary,
    DuplicateLink,
    DuplicateStatus,
    EvidenceItem,
    EvalRunSummary,
    GeocodeCacheEntry,
    GraphRun,
    IncidentExtraction,
    IngestionJob,
    InfoToken,
    MembershipStatus,
    OrgInvite,
    Organization,
    OrgMembership,
    OrgRole,
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
)
from app.repositories.base import Repository


class FirestoreRepository(Repository):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = firestore.Client(project=settings.firebase_project_id, database=settings.firestore_database)

    def _collection(self, name: str):
        return self.client.collection(name)

    def create_case(self, raw_input: str, source_channel: str, actor: UserContext) -> CaseRecord:
        case = CaseRecord(
            case_id=f"CASE-{uuid.uuid4().hex[:8].upper()}",
            org_id=actor.active_org_id,
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
                org_id=case.org_id,
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

            if assignment.team_id:
                team_ref = self._collection("teams").document(assignment.team_id)
                team_doc = team_ref.get(transaction=transaction)
                if team_doc.exists:
                    team = Team.model_validate(team_doc.to_dict())
                    team.active_dispatches += 1
                    team.availability_status = AvailabilityStatus.ON_MISSION
                    transaction.set(team_ref, team.model_dump(mode="json"))

            for volunteer_id in assignment.volunteer_ids:
                volunteer_ref = self._collection("volunteers").document(volunteer_id)
                volunteer_doc = volunteer_ref.get(transaction=transaction)
                if not volunteer_doc.exists:
                    continue
                volunteer = Volunteer.model_validate(volunteer_doc.to_dict())
                volunteer.active_assignments += 1
                volunteer.availability_status = AvailabilityStatus.ON_MISSION
                transaction.set(volunteer_ref, volunteer.model_dump(mode="json"))

            for resource_id in assignment.resource_ids:
                resource_ref = self._collection("resources").document(resource_id)
                resource_doc = resource_ref.get(transaction=transaction)
                if not resource_doc.exists:
                    continue
                resource = ResourceInventory.model_validate(resource_doc.to_dict())
                resource.quantity_available = max(resource.quantity_available - 1, 0)
                transaction.set(resource_ref, resource.model_dump(mode="json"))

            for allocation in assignment.resource_allocations:
                inventory_docs = (
                    self._collection("resources")
                    .where("resource_type", "==", allocation.resource_type)
                    .limit(10)
                    .stream(transaction=transaction)
                )
                for resource_doc in inventory_docs:
                    resource = ResourceInventory.model_validate(resource_doc.to_dict())
                    if resource.quantity_available <= 0:
                        continue
                    decrement = allocation.quantity or 1
                    resource.quantity_available = max(resource.quantity_available - decrement, 0)
                    transaction.set(resource_doc.reference, resource.model_dump(mode="json"))
                    break

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
        storage_bucket = self.settings.firebase_storage_bucket or "pending-bucket"
        evidence_id = f"evd-{uuid.uuid4().hex[:10]}"
        object_path = f"evidence/{actor.uid}/{evidence_id}/{payload.filename}"
        evidence = EvidenceItem(
            evidence_id=evidence_id,
            source_kind="UPLOAD",
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            storage_path=f"gs://{storage_bucket}/{object_path}",
            uploaded_by=actor.uid,
            linked_entity_type=payload.linked_entity_type,
            linked_entity_id=payload.linked_entity_id,
        )
        self._collection("evidence_items").document(evidence.evidence_id).set(evidence.model_dump(mode="json"))
        if payload.linked_entity_id:
            incident_ref = self._collection("incidents").document(payload.linked_entity_id)
            incident_doc = incident_ref.get()
            if incident_doc.exists:
                incident = CaseRecord.model_validate(incident_doc.to_dict())
                incident.evidence_ids = list(dict.fromkeys([*incident.evidence_ids, evidence.evidence_id]))
                incident_ref.set(incident.model_dump(mode="json"))
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
        if evidence.incident_id:
            incident_ref = self._collection("incidents").document(evidence.incident_id)
            incident_doc = incident_ref.get()
            if incident_doc.exists:
                incident = CaseRecord.model_validate(incident_doc.to_dict())
                incident.evidence_ids = list(dict.fromkeys([*incident.evidence_ids, evidence.evidence_id]))
                incident_ref.set(incident.model_dump(mode="json"))
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

    def get_user_profile_by_email(self, email: str) -> UserProfile | None:
        normalized = email.strip().lower()
        queries = [
            self._collection("users").where("email_normalized", "==", normalized).limit(1),
            self._collection("users").where("email", "==", normalized).limit(1),
            self._collection("users").where("email", "==", email.strip()).limit(1),
        ]
        for query in queries:
            docs = list(query.stream())
            if docs:
                return UserProfile.model_validate(docs[0].to_dict())
        return None

    def save_user_profile(self, profile: UserProfile) -> UserProfile:
        payload = profile.model_dump(mode="json")
        if profile.email:
            payload["email_normalized"] = profile.email.strip().lower()
        self._collection("users").document(profile.uid).set(payload, merge=True)
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
        self._collection("organizations").document(org_id).set(organization.model_dump(mode="json"))
        self._collection("org_memberships").document(membership.membership_id).set(membership.model_dump(mode="json"))
        profile = self.get_user_profile(actor.uid) or UserProfile(
            uid=actor.uid,
            email=actor.email,
            role=OrgRole.HOST,
            enabled=True,
        )
        profile.default_org_id = profile.default_org_id or org_id
        profile.org_ids = list(dict.fromkeys([*profile.org_ids, org_id]))
        profile.role_by_org[org_id] = OrgRole.HOST
        profile.role = OrgRole.HOST
        self.save_user_profile(profile)
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
        memberships_by_id = {
            doc.id: OrgMembership.model_validate(doc.to_dict())
            for doc in self._collection("org_memberships")
            .where("uid", "==", uid)
            .where("status", "==", MembershipStatus.ACTIVE)
            .stream()
        }
        if email:
            normalized = email.strip().lower()
            for doc in (
                self._collection("org_memberships")
                .where("email", "==", normalized)
                .where("status", "==", MembershipStatus.ACTIVE)
                .stream()
            ):
                membership = OrgMembership.model_validate(doc.to_dict())
                if membership.uid is None:
                    membership = self.bind_membership_uid(membership, uid)
                memberships_by_id[membership.membership_id] = membership
        memberships = list(memberships_by_id.values())
        organizations: list[Organization] = []
        for membership in memberships:
            org = self.get_organization(membership.org_id)
            if org is not None:
                organizations.append(org)
        return organizations, memberships

    def get_organization(self, org_id: str) -> Organization | None:
        doc = self._collection("organizations").document(org_id).get()
        if not doc.exists:
            return None
        return Organization.model_validate(doc.to_dict())

    def list_org_members(self, org_id: str) -> list[OrgMembership]:
        return [
            OrgMembership.model_validate(doc.to_dict())
            for doc in self._collection("org_memberships").where("org_id", "==", org_id).stream()
            if doc.to_dict().get("status") != MembershipStatus.REMOVED
        ]

    def list_org_invites(self, org_id: str) -> list[OrgInvite]:
        return [
            OrgInvite.model_validate(doc.to_dict())
            for doc in self._collection("org_invites")
            .where("org_id", "==", org_id)
            .where("status", "==", MembershipStatus.INVITED)
            .stream()
        ]

    def get_org_membership(self, org_id: str, uid: str | None = None, email: str | None = None) -> OrgMembership | None:
        if uid:
            docs = list(
                self._collection("org_memberships")
                .where("org_id", "==", org_id)
                .where("uid", "==", uid)
                .where("status", "==", MembershipStatus.ACTIVE)
                .limit(1)
                .stream()
            )
            if docs:
                return OrgMembership.model_validate(docs[0].to_dict())
        if email:
            normalized = email.strip().lower()
            docs = list(
                self._collection("org_memberships")
                .where("org_id", "==", org_id)
                .where("email", "==", normalized)
                .where("status", "==", MembershipStatus.ACTIVE)
                .limit(1)
                .stream()
            )
            if docs:
                return OrgMembership.model_validate(docs[0].to_dict())
        return None

    def create_org_invite(self, org_id: str, email: str, role: OrgRole, actor: UserContext) -> OrgInvite:
        normalized = email.strip().lower()
        if self.get_org_membership(org_id, email=normalized) is None:
            membership = OrgMembership(
                membership_id=f"{org_id}-invite-{uuid.uuid4().hex[:8]}",
                org_id=org_id,
                email=normalized,
                role=role,
                status=MembershipStatus.ACTIVE,
                invited_by=actor.uid,
                joined_at=None,
            )
            self._collection("org_memberships").document(membership.membership_id).set(membership.model_dump(mode="json"))
        invite = OrgInvite(
            invite_id=f"inv-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            email=normalized,
            role=role,
            invited_by=actor.uid,
        )
        self._collection("org_invites").document(invite.invite_id).set(invite.model_dump(mode="json"))
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
        ref = self._collection("org_memberships").document(membership_id)
        doc = ref.get()
        membership = OrgMembership.model_validate(doc.to_dict())
        if membership.org_id != org_id:
            raise KeyError(membership_id)
        if role is not None:
            membership.role = role
        if status is not None:
            membership.status = status
            if status in {MembershipStatus.DISABLED, MembershipStatus.REMOVED}:
                membership.disabled_at = datetime.now(tz=UTC)
        ref.set(membership.model_dump(mode="json"))
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
        membership.joined_at = membership.joined_at or datetime.now(tz=UTC)
        self._collection("org_memberships").document(membership.membership_id).set(membership.model_dump(mode="json"))
        return membership

    def record_audit_event(self, event: AuditEvent) -> None:
        self._collection("audit_events").document(event.audit_id).set(event.model_dump(mode="json"))

    def save_graph_run(self, run: GraphRun) -> GraphRun:
        run.updated_at = datetime.now(tz=UTC)
        self._collection("agent_runs").document(run.run_id).set(run.model_dump(mode="json"))
        return run

    def get_graph_run(self, run_id: str) -> GraphRun:
        doc = self._collection("agent_runs").document(run_id).get()
        return GraphRun.model_validate(doc.to_dict())

    def save_vector_records(self, records: list[VectorRecord]) -> list[VectorRecord]:
        batch = self.client.batch()
        for record in records:
            batch.set(self._collection("vector_records").document(record.vector_id), record.model_dump(mode="json"))
        batch.commit()
        return records

    def search_vector_records(self, org_id: str, query_embedding: list[float], limit: int = 8) -> list[VectorRecord]:
        records = [
            VectorRecord.model_validate(doc.to_dict())
            for doc in self._collection("vector_records")
            .where("org_id", "==", org_id)
            .where("status", "==", "ACTIVE")
            .limit(100)
            .stream()
        ]
        records = [item for item in records if item.deleted_at is None]
        if query_embedding:
            records.sort(key=lambda item: self._cosine(query_embedding, item.embedding), reverse=True)
        return records[:limit]

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
        doc = self._collection("geocode_cache").document(cache_key).get()
        if not doc.exists:
            return None
        return GeocodeCacheEntry.model_validate(doc.to_dict())

    def save_geocode_cache(self, entry: GeocodeCacheEntry) -> GeocodeCacheEntry:
        payload = entry.model_dump(mode="json")
        payload["updated_at"] = datetime.now(tz=UTC).isoformat()
        self._collection("geocode_cache").document(entry.cache_key).set(payload)
        return GeocodeCacheEntry.model_validate(payload)
