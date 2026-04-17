from __future__ import annotations

import csv
import hashlib
import io
import uuid
import re
from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - fallback keeps local demos alive if optional runtime breaks.
    END = "__end__"
    StateGraph = None  # type: ignore[assignment]

from app.models.domain import (
    AssignmentDecision,
    AuditEvent,
    AvailabilityStatus,
    CategoryKind,
    CaseEvent,
    CaseStatus,
    DraftRecordType,
    GeoPoint,
    GraphRun,
    GraphRunRequest,
    GraphRunStatus,
    IncidentExtraction,
    InfoTokenType,
    LocationConfidence,
    RecordDraft,
    ResourceInventory,
    SourceArtifact,
    Team,
    UserContext,
    UserQuestion,
    VectorRecord,
)
from app.repositories.base import Repository
from app.services.docling_parser import DoclingParserService
from app.services.extractor import ExtractionService
from app.services.matching import MatchingService
from app.services.scoring import ScoringService
from app.services.tokens import TokenService
from app.services.vectors import VectorService


class AgentGraphState(TypedDict, total=False):
    payload: GraphRunRequest
    actor: UserContext
    source_text: str
    source_kind: str
    parsed: Any
    artifact: SourceArtifact
    normalized_markdown: str
    cleaned_markdown: str
    draft: RecordDraft
    questions: list[UserQuestion]
    case_id: str
    case: Any
    context_records: list[VectorRecord]
    recommendations: list[Any]
    unassigned_reason: str | None
    run: GraphRun


class AgentGraphService:
    def __init__(
        self,
        repository: Repository,
        docling: DoclingParserService,
        extractor: ExtractionService,
        scorer: ScoringService,
        matcher: MatchingService,
        token_service: TokenService,
        vector_service: VectorService,
    ) -> None:
        self.repository = repository
        self.docling = docling
        self.extractor = extractor
        self.scorer = scorer
        self.matcher = matcher
        self.token_service = token_service
        self.vector_service = vector_service
        self.source_graph = self._compile_source_graph()
        self.dispatch_graph = self._compile_dispatch_graph()

    def run_graph1(self, payload: GraphRunRequest, actor: UserContext) -> GraphRun:
        if self.source_graph is not None:
            state = self.source_graph.invoke({"payload": payload, "actor": actor})
            return state["run"]
        return self._graph1_preview_node(
            self._graph1_geocode_node(
                self._graph1_gemini_draft_node(
                    self._graph1_prune_redact_node(
                        self._graph1_document_normalizer_node(
                            self._graph1_docling_parse_node(self._graph1_source_loader_node({"payload": payload, "actor": actor}))
                        )
                    )
                )
            )
        )["run"]

    def run_graph1_file(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        source_kind: str,
        target: str,
        operator_prompt: str | None,
        actor: UserContext,
    ) -> GraphRun:
        org_id = actor.active_org_id or "unassigned"
        normalized_kind = (source_kind or "CSV").upper()
        warnings: list[str] = []
        text = ""
        parsed_structured: dict[str, Any] = {}
        detected_languages = ["en"]
        ocr_used = False

        if normalized_kind == "CSV" or filename.lower().endswith(".csv"):
            text = content.decode("utf-8-sig")
            drafts, csv_warnings = self._drafts_from_csv_text(text, target, operator_prompt)
            warnings.extend(csv_warnings)
            parsed_structured = {"source_kind": "CSV", "row_count": len(drafts)}
        else:
            parsed = self.docling.parse_bytes(filename, content_type, content)
            text = self._prune_and_redact(parsed.markdown)
            parsed_structured = parsed.structured
            warnings.extend(parsed.warnings)
            detected_languages = parsed.detected_languages
            ocr_used = parsed.ocr_used
            payload = GraphRunRequest(
                source_kind=normalized_kind,
                target=target,
                text=text,
                operator_prompt=operator_prompt,
            )
            drafts = [self._draft_from_payload(payload, text, parse_warnings=warnings)]

        artifact = SourceArtifact(
            artifact_id=f"art-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            source_kind=normalized_kind,
            filename=filename,
            text=text[:12000],
            docling_markdown=text,
            docling_json=parsed_structured,
            parse_status="COMPLETED",
            parse_warnings=warnings,
            detected_languages=detected_languages,
            ocr_used=ocr_used,
        )
        questions = self._questions_for_drafts(drafts)
        run = GraphRun(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            graph_name="source_to_operational_records_graph",
            status=GraphRunStatus.WAITING_FOR_CONFIRMATION,
            created_by=actor.uid,
            source_artifacts=[artifact],
            drafts=drafts,
            user_questions=questions,
            needs_user_input=False,
            next_action="confirm_or_edit",
        )
        return self.repository.save_graph_run(run)

    def _graph1_source_loader_node(self, state: AgentGraphState) -> AgentGraphState:
        payload = state["payload"]
        return {"source_text": payload.text or "", "source_kind": payload.source_kind}

    def _graph1_docling_parse_node(self, state: AgentGraphState) -> AgentGraphState:
        payload = state["payload"]
        actor = state["actor"]
        parsed = self.docling.parse_text(state.get("source_text", ""), state.get("source_kind", payload.source_kind))
        artifact = SourceArtifact(
            artifact_id=f"art-{uuid.uuid4().hex[:10]}",
            org_id=actor.active_org_id or "unassigned",
            source_kind=payload.source_kind,
            filename=None,
            text=payload.text,
            docling_markdown=parsed.markdown,
            docling_json=parsed.structured,
            parse_status="COMPLETED",
            parse_warnings=parsed.warnings,
            detected_languages=parsed.detected_languages,
            ocr_used=parsed.ocr_used,
        )
        return {"parsed": parsed, "artifact": artifact}

    def _graph1_document_normalizer_node(self, state: AgentGraphState) -> AgentGraphState:
        parsed = state["parsed"]
        markdown = parsed.markdown or state.get("source_text", "")
        return {"normalized_markdown": markdown.strip()}

    def _graph1_prune_redact_node(self, state: AgentGraphState) -> AgentGraphState:
        cleaned = self._prune_and_redact(state.get("normalized_markdown", ""))
        return {"cleaned_markdown": cleaned}

    def _graph1_gemini_draft_node(self, state: AgentGraphState) -> AgentGraphState:
        payload = state["payload"]
        artifact = state.get("artifact")
        draft = self._draft_from_payload(
            payload,
            state.get("cleaned_markdown", ""),
            parse_warnings=artifact.parse_warnings if artifact else [],
        )
        return {"draft": draft}

    def _graph1_geocode_node(self, state: AgentGraphState) -> AgentGraphState:
        draft = state["draft"]
        questions: list[UserQuestion] = []
        if draft.draft_type == DraftRecordType.INCIDENT and draft.payload.get("location_confidence") == "UNKNOWN":
            questions.append(
                UserQuestion(
                    question_id="location",
                    question="Confirm the exact incident location with an address or map pin before dispatch.",
                    field="location_text",
                )
            )
        return {"questions": questions}

    def _graph1_preview_node(self, state: AgentGraphState) -> AgentGraphState:
        actor = state["actor"]
        run = GraphRun(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            org_id=actor.active_org_id or "unassigned",
            graph_name="source_to_operational_records_graph",
            status=GraphRunStatus.WAITING_FOR_CONFIRMATION,
            created_by=actor.uid,
            source_artifacts=[state["artifact"]],
            drafts=[state["draft"]],
            user_questions=state.get("questions", []),
            needs_user_input=False,
            next_action="confirm_or_edit",
        )
        return {"run": self.repository.save_graph_run(run)}

    def _compile_source_graph(self) -> Any | None:
        if StateGraph is None:
            return None
        graph = StateGraph(AgentGraphState)
        graph.add_node("source_loader_node", self._graph1_source_loader_node)
        graph.add_node("docling_parse_node", self._graph1_docling_parse_node)
        graph.add_node("document_normalizer_node", self._graph1_document_normalizer_node)
        graph.add_node("prune_redact_node", self._graph1_prune_redact_node)
        graph.add_node("gemini_draft_node", self._graph1_gemini_draft_node)
        graph.add_node("geocode_node", self._graph1_geocode_node)
        graph.add_node("preview_node", self._graph1_preview_node)
        graph.set_entry_point("source_loader_node")
        graph.add_edge("source_loader_node", "docling_parse_node")
        graph.add_edge("docling_parse_node", "document_normalizer_node")
        graph.add_edge("document_normalizer_node", "prune_redact_node")
        graph.add_edge("prune_redact_node", "gemini_draft_node")
        graph.add_edge("gemini_draft_node", "geocode_node")
        graph.add_edge("geocode_node", "preview_node")
        graph.add_edge("preview_node", END)
        return graph.compile()

    def _compile_dispatch_graph(self) -> Any | None:
        if StateGraph is None:
            return None
        graph = StateGraph(AgentGraphState)
        graph.add_node("retrieve_context_node", self._graph2_retrieve_context_node)
        graph.add_node("supervisor_node", self._graph2_supervisor_node)
        graph.add_node("planning_node", self._graph2_planning_node)
        graph.add_node("maps_eta_node", self._graph2_maps_eta_node)
        graph.add_node("assignment_preview_node", self._graph2_assignment_preview_node)
        graph.set_entry_point("retrieve_context_node")
        graph.add_edge("retrieve_context_node", "supervisor_node")
        graph.add_conditional_edges(
            "supervisor_node",
            self._graph2_supervisor_route,
            {"pause": "assignment_preview_node", "plan": "planning_node"},
        )
        graph.add_edge("planning_node", "maps_eta_node")
        graph.add_edge("maps_eta_node", "assignment_preview_node")
        graph.add_edge("assignment_preview_node", END)
        return graph.compile()

    def _graph2_retrieve_context_node(self, state: AgentGraphState) -> AgentGraphState:
        payload = state["payload"]
        actor = state["actor"]
        org_id = actor.active_org_id or "unassigned"
        case_id = payload.linked_case_id or payload.text.strip()
        case = self.repository.get_case(case_id)
        query = payload.text or case.raw_input
        context_records = self.repository.search_vector_records(org_id, self.vector_service.embed(query), limit=8)
        return {"case_id": case_id, "case": case, "context_records": context_records}

    def _graph2_supervisor_node(self, state: AgentGraphState) -> AgentGraphState:
        actor = state["actor"]
        org_id = actor.active_org_id or "unassigned"
        case = state["case"]
        if case.org_id != org_id:
            raise PermissionError("Incident belongs to another organization.")
        questions: list[UserQuestion] = []
        if (case.geo is None and not case.location_text) or case.location_confidence == "UNKNOWN":
            questions.append(
                UserQuestion(
                    question_id="confirm_location",
                    question="Incident location is missing or ambiguous. Provide an exact address or map pin.",
                    field="location_text",
                )
            )
        return {"questions": questions}

    def _graph2_supervisor_route(self, state: AgentGraphState) -> str:
        return "pause" if state.get("questions") else "plan"

    def _graph2_planning_node(self, state: AgentGraphState) -> AgentGraphState:
        case = state["case"]
        org_id = state["actor"].active_org_id
        teams = [team for team in self.repository.list_teams() if team.org_id == org_id]
        volunteers = [volunteer for volunteer in self.repository.list_volunteers() if volunteer.org_id == org_id]
        resources = [resource for resource in self.repository.list_resources() if resource.org_id == org_id]
        recommendations, reason = self.matcher.recommend(case, teams, volunteers, resources)
        return {"recommendations": recommendations, "unassigned_reason": reason}

    def _graph2_maps_eta_node(self, state: AgentGraphState) -> AgentGraphState:
        # ETA enrichment already happens inside MatchingService. This node stays explicit
        # so route-matrix logic can be swapped in without changing API contracts.
        return {}

    def _graph2_assignment_preview_node(self, state: AgentGraphState) -> AgentGraphState:
        actor = state["actor"]
        org_id = actor.active_org_id or "unassigned"
        if state.get("questions"):
            case = state.get("case")
            run = GraphRun(
                run_id=f"run-{uuid.uuid4().hex[:10]}",
                org_id=org_id,
                graph_name="dispatch_assignment_graph",
                status=GraphRunStatus.WAITING_FOR_USER,
                created_by=actor.uid,
                drafts=[
                    RecordDraft(
                        draft_id=f"draft-{uuid.uuid4().hex[:10]}",
                        draft_type=DraftRecordType.DISPATCH,
                        title=f"Blocked dispatch plan for {case.case_id if case else 'incident'}",
                        payload={
                            "case_id": case.case_id if case else None,
                            "blocked_reason": "missing_or_ambiguous_location",
                        },
                        confidence=0.2,
                        warnings=[question.question for question in state["questions"]],
                    )
                ],
                user_questions=state["questions"],
                needs_user_input=True,
                next_action="pause",
            )
            return {"run": self.repository.save_graph_run(run)}
        case = state["case"]
        recommendations = state.get("recommendations", [])
        reason = state.get("unassigned_reason")
        draft = RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.DISPATCH,
            title=f"Dispatch plan for {case.case_id}",
            payload={
                "case_id": case.case_id,
                "recommendations": [item.model_dump(mode="json") for item in recommendations],
                "unassigned_reason": reason,
                "context_records": [item.record_id for item in state.get("context_records", [])],
            },
            confidence=0.8 if recommendations else 0.35,
            warnings=[] if recommendations else [reason or "No feasible dispatch option found."],
        )
        run = GraphRun(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            graph_name="dispatch_assignment_graph",
            status=GraphRunStatus.WAITING_FOR_CONFIRMATION,
            created_by=actor.uid,
            drafts=[draft],
            next_action="confirm_or_edit",
        )
        return {"run": self.repository.save_graph_run(run)}

    def edit_graph_run(
        self,
        run_id: str,
        prompt: str,
        actor: UserContext,
        draft_id: str | None = None,
        field_updates: dict[str, Any] | None = None,
    ) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        for draft in run.drafts:
            if draft_id is None or draft.draft_id == draft_id:
                draft.frozen = True
                changed_fields: list[str] = []
                if prompt.strip():
                    if draft.draft_type == DraftRecordType.INCIDENT:
                        self._reevaluate_incident_draft(draft, prompt)
                    elif draft.draft_type == DraftRecordType.TEAM:
                        self._reevaluate_team_draft(draft, prompt)
                    elif draft.draft_type == DraftRecordType.RESOURCE:
                        self._reevaluate_resource_draft(draft, prompt)
                    else:
                        draft.payload["operator_prompt"] = prompt
                        draft.warnings = [*draft.warnings, f"Reevaluated with operator prompt: {prompt}"]
                        draft.confidence = min(1.0, draft.confidence + 0.03)
                    changed_fields.append("operator_prompt")
                changed_fields.extend(self._apply_field_updates(draft, field_updates or {}))
                draft.changed_fields = list(dict.fromkeys([*draft.changed_fields, *changed_fields]))
                self._refresh_draft_display(draft)
                draft.frozen = False
        run.status = GraphRunStatus.WAITING_FOR_CONFIRMATION
        run.next_action = "confirm_or_edit"
        return self.repository.save_graph_run(run)

    def remove_draft(self, run_id: str, draft_id: str, reason: str | None, actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        for draft in run.drafts:
            if draft.draft_id == draft_id:
                draft.removed = True
                draft.warnings = [*draft.warnings, f"Removed before commit: {reason or 'operator request'}"]
        return self.repository.save_graph_run(run)

    def confirm_graph1(self, run_id: str, actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        for draft in run.drafts:
            if draft.removed:
                continue
            if draft.draft_type == DraftRecordType.INCIDENT:
                raw_input = draft.payload.get("raw_input", draft.title)
                source_hash = self._source_hash("INCIDENT", raw_input)
                duplicate = self._find_duplicate_case(raw_input, source_hash, run.org_id)
                if duplicate is not None:
                    draft.warnings = [*draft.warnings, f"Duplicate incident detected; reused {duplicate.case_id}."]
                    run.committed_record_ids.append(duplicate.case_id)
                    continue
                case = self.repository.create_case(raw_input, "GRAPH1_CONFIRM", actor, source_hash=source_hash)
                extraction = IncidentExtraction.model_validate(
                    draft.payload.get("extracted") or self.extractor.extract(raw_input).model_dump(mode="json")
                )
                case_status = CaseStatus.NEEDS_REVIEW if extraction.confidence < 0.4 else CaseStatus.EXTRACTED
                case = self.repository.save_extraction(case.case_id, extraction, case_status)
                geo_payload = draft.payload.get("geo")
                if isinstance(geo_payload, dict):
                    lat = geo_payload.get("lat")
                    lng = geo_payload.get("lng")
                    if isinstance(lat, int | float) and isinstance(lng, int | float):
                        case = self.repository.update_case_location(
                            case.case_id,
                            extraction.location_text,
                            float(lat),
                            float(lng),
                            LocationConfidence.EXACT,
                        )
                if extraction.confidence >= 0.4:
                    rationale = self.scorer.score(extraction)
                    case = self.repository.save_scoring(case.case_id, rationale.final_score, rationale, rationale.final_urgency)
                tokens = self.token_service.from_incident(case, extraction)
                self.repository.save_info_tokens(case.case_id, tokens)
                self.repository.save_vector_records(
                    [
                        VectorRecord(
                            vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                            org_id=run.org_id,
                            record_type="INCIDENT",
                            record_id=case.case_id,
                            token_id=tokens[0].token_id if tokens else None,
                            embedding=self.vector_service.embed(f"{case.raw_input} {extraction.notes_for_dispatch}"),
                            text=f"{case.raw_input}\n{extraction.notes_for_dispatch}",
                            metadata={"category": extraction.category, "urgency": extraction.urgency},
                            source_refs=[artifact.artifact_id for artifact in run.source_artifacts],
                            created_by=actor.uid,
                        )
                    ]
                )
                self.repository.record_audit_event(
                    AuditEvent(
                        audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                        org_id=run.org_id,
                        actor_uid=actor.uid,
                        action="GRAPH1_INCIDENT_COMMITTED",
                        object_ref=case.case_id,
                        payload={"run_id": run.run_id, "provider_used": draft.payload.get("provider_used")},
                    )
                )
                self.repository.record_event(
                    CaseEvent(
                        event_id=f"evt-{uuid.uuid4().hex[:10]}",
                        org_id=run.org_id,
                        case_id=case.case_id,
                        event_type="GRAPH1_COMMITTED",
                        actor_uid=actor.uid,
                        payload={"run_id": run.run_id},
                    )
                )
                run.committed_record_ids.append(case.case_id)
            elif draft.draft_type == DraftRecordType.TEAM:
                team = Team.model_validate(draft.payload["team"])
                team.org_id = run.org_id
                self.repository.save_team(team)
                tokens = self.token_service.from_csv_row(
                    run.run_id,
                    self._stringify_values(draft.payload.get("source_row") or draft.payload.get("team") or {}),
                    InfoTokenType.TEAM_CAPABILITY,
                    "TEAM",
                    team.team_id,
                )
                for token in tokens:
                    token.org_id = run.org_id
                self.repository.save_info_tokens(None, tokens)
                self.repository.save_vector_records(
                    [
                        VectorRecord(
                            vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                            org_id=run.org_id,
                            record_type="TEAM",
                            record_id=team.team_id,
                            token_id=tokens[0].token_id if tokens else None,
                            embedding=self.vector_service.embed(f"{team.display_name} {' '.join(team.capability_tags)} {team.base_label}"),
                            text=f"{team.display_name}\n{', '.join(team.capability_tags)}\n{team.base_label}",
                            metadata={"capabilities": team.capability_tags, "availability": team.availability_status.value},
                            source_refs=[artifact.artifact_id for artifact in run.source_artifacts],
                            created_by=actor.uid,
                        )
                    ]
                )
                self.repository.record_audit_event(
                    AuditEvent(
                        audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                        org_id=run.org_id,
                        actor_uid=actor.uid,
                        action="GRAPH1_TEAM_COMMITTED",
                        object_ref=team.team_id,
                        payload={"run_id": run.run_id},
                    )
                )
                run.committed_record_ids.append(team.team_id)
            elif draft.draft_type == DraftRecordType.RESOURCE:
                resource = ResourceInventory.model_validate(draft.payload["resource"])
                resource.org_id = run.org_id
                self.repository.save_resource(resource)
                tokens = self.token_service.from_csv_row(
                    run.run_id,
                    self._stringify_values(draft.payload.get("source_row") or draft.payload.get("resource") or {}),
                    InfoTokenType.RESOURCE_CAPABILITY,
                    "RESOURCE",
                    resource.resource_id,
                )
                for token in tokens:
                    token.org_id = run.org_id
                self.repository.save_info_tokens(None, tokens)
                self.repository.save_vector_records(
                    [
                        VectorRecord(
                            vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                            org_id=run.org_id,
                            record_type="RESOURCE",
                            record_id=resource.resource_id,
                            token_id=tokens[0].token_id if tokens else None,
                            embedding=self.vector_service.embed(f"{resource.resource_type} {resource.location_label} {resource.quantity_available}"),
                            text=f"{resource.resource_type}\n{resource.location_label}\nQuantity {resource.quantity_available}",
                            metadata={"resource_type": resource.resource_type, "quantity_available": resource.quantity_available},
                            source_refs=[artifact.artifact_id for artifact in run.source_artifacts],
                            created_by=actor.uid,
                        )
                    ]
                )
                self.repository.record_audit_event(
                    AuditEvent(
                        audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                        org_id=run.org_id,
                        actor_uid=actor.uid,
                        action="GRAPH1_RESOURCE_COMMITTED",
                        object_ref=resource.resource_id,
                        payload={"run_id": run.run_id},
                    )
                )
                run.committed_record_ids.append(resource.resource_id)
        run.status = GraphRunStatus.COMMITTED
        run.next_action = "complete"
        return self.repository.save_graph_run(run)

    def run_graph2(self, payload: GraphRunRequest, actor: UserContext) -> GraphRun:
        if self.dispatch_graph is not None:
            state = self.dispatch_graph.invoke({"payload": payload, "actor": actor})
            return state["run"]
        state = self._graph2_retrieve_context_node({"payload": payload, "actor": actor})
        state.update(self._graph2_supervisor_node({"payload": payload, "actor": actor, **state}))
        if state.get("questions"):
            return self._graph2_assignment_preview_node({"payload": payload, "actor": actor, **state})["run"]
        state.update(self._graph2_planning_node({"payload": payload, "actor": actor, **state}))
        state.update(self._graph2_maps_eta_node({"payload": payload, "actor": actor, **state}))
        return self._graph2_assignment_preview_node({"payload": payload, "actor": actor, **state})["run"]

    def resume_graph2(self, run_id: str, answers: dict[str, str], actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        case_id = next(
            (
                str(draft.payload.get("case_id"))
                for draft in run.drafts
                if draft.draft_type == DraftRecordType.DISPATCH and draft.payload.get("case_id")
            ),
            "",
        )
        if case_id:
            location_answer = answers.get("confirm_location") or answers.get("location") or answers.get("location_text")
            if location_answer:
                self.repository.update_case_location(
                    case_id,
                    location_answer,
                    None,
                    None,
                    LocationConfidence.APPROXIMATE,
                )
            case = self.repository.get_case(case_id)
            rerun = self.run_graph2(GraphRunRequest(linked_case_id=case_id, text=case.raw_input), actor)
            rerun.run_id = run.run_id
            rerun.created_at = run.created_at
            rerun.user_answers.update(answers)
            rerun.needs_user_input = False
            rerun.user_questions = []
            rerun.next_action = "confirm_or_edit" if rerun.status == GraphRunStatus.WAITING_FOR_CONFIRMATION else rerun.next_action
            return self.repository.save_graph_run(rerun)
        run.user_answers.update(answers)
        run.needs_user_input = False
        run.status = GraphRunStatus.WAITING_FOR_CONFIRMATION
        run.next_action = "reevaluate"
        run.user_questions = []
        return self.repository.save_graph_run(run)

    def confirm_graph2(self, run_id: str, actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        for draft in run.drafts:
            if draft.draft_type != DraftRecordType.DISPATCH or draft.removed:
                continue
            recommendations = draft.payload.get("recommendations") or []
            if not recommendations:
                draft.warnings.append("Cannot confirm dispatch without recommendations.")
                run.status = GraphRunStatus.WAITING_FOR_USER
                return self.repository.save_graph_run(run)
            top = recommendations[0]
            assignment = AssignmentDecision(
                assignment_id=f"asg-{uuid.uuid4().hex[:10]}",
                org_id=run.org_id,
                case_id=top.get("case_id") or draft.payload.get("case_id"),
                incident_id=draft.payload.get("case_id"),
                team_id=top.get("team_id"),
                volunteer_ids=top.get("volunteer_ids", []),
                resource_ids=top.get("resource_ids", []),
                resource_allocations=top.get("resource_allocations", []),
                match_score=top.get("match_score", 0.5),
                eta_minutes=top.get("eta_minutes"),
                route_summary=top.get("route_summary"),
                confirmed_by=actor.uid,
            )
            self.repository.create_assignment(assignment)
            run.committed_record_ids.append(assignment.assignment_id)
        run.status = GraphRunStatus.COMMITTED
        run.next_action = "complete"
        return self.repository.save_graph_run(run)

    def _draft_from_payload(
        self,
        payload: GraphRunRequest,
        markdown: str,
        parse_warnings: list[str] | None = None,
    ) -> RecordDraft:
        if payload.target == "teams":
            return self._team_draft_from_row({"display_name": "Team capability draft", "notes": markdown}, payload.operator_prompt)
        if payload.target == "resources":
            return self._resource_draft_from_row({"resource_type": "UNKNOWN_RESOURCE", "location_label": markdown}, payload.operator_prompt)
        result = self.extractor.extract_with_metadata(markdown)
        extraction = result.extraction
        warnings = [
            *result.warnings,
            *(parse_warnings or []),
            *extraction.data_quality.needs_followup_questions,
        ]
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.INCIDENT,
            title=f"{extraction.category} - {extraction.location_text or 'Location pending'}",
            payload={
                "raw_input": markdown,
                "extracted": extraction.model_dump(mode="json"),
                "location_confidence": "UNKNOWN" if extraction.data_quality.missing_location else "APPROXIMATE",
                "operator_prompt": payload.operator_prompt,
                "provider_used": result.provider_used,
                "provider_fallbacks": result.provider_fallbacks,
                "parse_warnings": parse_warnings or [],
                "schema_validated": result.schema_validated,
            },
            confidence=extraction.confidence,
            warnings=list(dict.fromkeys(warnings)),
            display_fields=self._incident_display_fields(extraction, None),
            map_status=LocationConfidence.UNKNOWN if extraction.data_quality.missing_location else LocationConfidence.APPROXIMATE,
        )

    def _drafts_from_csv_text(
        self,
        text: str,
        target: str,
        operator_prompt: str | None,
    ) -> tuple[list[RecordDraft], list[str]]:
        warnings: list[str] = []
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return [], ["CSV has no headers."]

        normalized_headers = [header.strip() for header in reader.fieldnames if header]
        if len(normalized_headers) != len(set(header.lower() for header in normalized_headers)):
            warnings.append("CSV contains duplicate headers; later values may overwrite earlier values.")

        drafts: list[RecordDraft] = []
        seen_rows: set[str] = set()
        for row_index, row in enumerate(reader, start=1):
            cleaned = {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
            row_key = "|".join(cleaned.get(header, "") for header in normalized_headers)
            if not row_key.strip():
                continue
            if row_key in seen_rows:
                warnings.append(f"Skipped duplicate row {row_index}.")
                continue
            if not self._row_matches_target(cleaned, target):
                warnings.append(f"Skipped row {row_index}: no {target} fields found.")
                continue
            seen_rows.add(row_key)
            try:
                if target == "teams":
                    drafts.append(self._team_draft_from_row(cleaned, operator_prompt, row_index))
                elif target == "resources":
                    drafts.append(self._resource_draft_from_row(cleaned, operator_prompt, row_index))
                else:
                    drafts.append(self._incident_draft_from_row(cleaned, operator_prompt, row_index))
            except Exception as exc:
                warnings.append(f"Row {row_index} could not be drafted: {type(exc).__name__}: {exc}")
        if not drafts:
            warnings.append("No usable rows were found in the CSV.")
        return drafts, warnings

    def _incident_draft_from_row(self, row: dict[str, str], operator_prompt: str | None, row_index: int | None = None) -> RecordDraft:
        raw_input = row.get("raw_input") or row.get("description") or row.get("incident") or " | ".join(row.values())
        if row.get("location_text") and row.get("location_text") not in raw_input:
            raw_input = f"{raw_input}\nLocation: {row['location_text']}"
        if row.get("required_capabilities"):
            raw_input = f"{raw_input}\nRequired capabilities: {row['required_capabilities']}"
        if row.get("required_resources"):
            raw_input = f"{raw_input}\nRequired resources: {row['required_resources']}"
        feature_lines = []
        for key, label in [
            ("hazard_type", "Hazard"),
            ("people_affected", "People affected"),
            ("priority_feature", "Priority feature"),
            ("road_access", "Road access"),
            ("vulnerable_groups", "Vulnerable groups"),
            ("source_confidence", "Source confidence"),
            ("map_feature", "Map feature"),
        ]:
            if row.get(key):
                feature_lines.append(f"{label}: {row[key]}")
        if feature_lines:
            raw_input = f"{raw_input}\n" + "\n".join(feature_lines)
        if operator_prompt:
            raw_input = f"{raw_input}\nOperator instruction: {operator_prompt}"
        result = self.extractor.extract_with_metadata(self._prune_and_redact(raw_input))
        extraction = result.extraction
        if row.get("location_text") and not extraction.location_text:
            extraction.location_text = row["location_text"]
            extraction.data_quality.missing_location = False
        if row.get("category"):
            normalized_category = row["category"].strip().upper()
            if normalized_category in {item.value for item in CategoryKind}:
                extraction.category = CategoryKind(normalized_category)
        geo = self._geo_from_row(row)
        location_confidence = (
            "EXACT"
            if geo is not None
            else "UNKNOWN" if extraction.data_quality.missing_location else "APPROXIMATE"
        )
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.INCIDENT,
            title=f"{extraction.category} - {extraction.location_text or 'Location pending'}",
            payload={
                "raw_input": raw_input,
                "source_row": row,
                "extracted": extraction.model_dump(mode="json"),
                "geo": geo.model_dump(mode="json") if geo is not None else None,
                "location_confidence": location_confidence,
                "operator_prompt": operator_prompt,
                "provider_used": result.provider_used,
                "provider_fallbacks": result.provider_fallbacks,
                "parse_warnings": result.warnings,
                "schema_validated": result.schema_validated,
            },
            confidence=extraction.confidence,
            warnings=list(dict.fromkeys([*result.warnings, *extraction.data_quality.needs_followup_questions])),
            source_row_index=row_index,
            display_fields=self._incident_display_fields(extraction, geo),
            map_status=LocationConfidence(location_confidence),
        )

    def _team_draft_from_row(self, row: dict[str, str], operator_prompt: str | None, row_index: int | None = None) -> RecordDraft:
        team_id = row.get("team_id") or f"TEAM-{uuid.uuid4().hex[:8].upper()}"
        capabilities = self._split_tags(row.get("capability_tags") or row.get("skills") or row.get("capabilities"))
        members = self._split_tags(row.get("member_ids"))
        service_radius = self._parse_float(row.get("service_radius_km"), 30.0)
        team = Team(
            team_id=team_id,
            display_name=row.get("display_name") or row.get("name") or team_id,
            capability_tags=capabilities or ["GENERAL_RESPONSE"],
            member_ids=members,
            service_radius_km=service_radius,
            base_label=row.get("base_label") or row.get("location") or row.get("current_label") or "Location pending",
            base_geo=self._geo_from_row(row, "base") or self._geo_from_row(row),
            current_label=row.get("current_label") or row.get("base_label") or row.get("location"),
            current_geo=self._geo_from_row(row, "current") or self._geo_from_row(row, "base") or self._geo_from_row(row),
            availability_status=self._availability(row.get("availability_status") or row.get("status")),
            reliability_score=self._parse_float(row.get("reliability_score"), 0.8),
            notes=[operator_prompt] if operator_prompt else [],
        )
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.TEAM,
            title=f"{team.display_name} ({', '.join(team.capability_tags[:2])})",
            payload={
                "raw_input": " | ".join(value for value in row.values() if value),
                "source_row": row,
                "team": team.model_dump(mode="json"),
                "operator_prompt": operator_prompt,
                "provider_used": "CSV Parser",
                "provider_fallbacks": [],
                "parse_warnings": [],
                "schema_validated": True,
            },
            confidence=0.78,
            warnings=[] if team.base_label != "Location pending" else ["Team base location is missing."],
            source_row_index=row_index,
            display_fields=self._team_display_fields(team),
            map_status=LocationConfidence.EXACT if (team.current_geo or team.base_geo) else LocationConfidence.UNKNOWN,
        )

    def _resource_draft_from_row(self, row: dict[str, str], operator_prompt: str | None, row_index: int | None = None) -> RecordDraft:
        resource_id = row.get("resource_id") or f"RES-{uuid.uuid4().hex[:8].upper()}"
        resource = ResourceInventory(
            resource_id=resource_id,
            owning_team_id=row.get("owning_team_id") or None,
            resource_type=row.get("resource_type") or row.get("category") or "UNKNOWN_RESOURCE",
            quantity_available=max(self._parse_float(row.get("quantity_available") or row.get("quantity"), 0.0), 0.0),
            location_label=row.get("location_label") or row.get("location") or "Location pending",
            location=self._geo_from_row(row, "location") or self._geo_from_row(row),
            current_label=row.get("current_label") or row.get("location_label") or row.get("location"),
            current_geo=self._geo_from_row(row, "current") or self._geo_from_row(row, "location") or self._geo_from_row(row),
            constraints=self._split_tags(row.get("constraints")),
            evidence_ids=[],
        )
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.RESOURCE,
            title=f"{resource.resource_type} ({resource.quantity_available:g} available)",
            payload={
                "raw_input": " | ".join(value for value in row.values() if value),
                "source_row": row,
                "resource": resource.model_dump(mode="json"),
                "operator_prompt": operator_prompt,
                "provider_used": "CSV Parser",
                "provider_fallbacks": [],
                "parse_warnings": [],
                "schema_validated": True,
            },
            confidence=0.78 if resource.quantity_available > 0 else 0.45,
            warnings=[] if resource.location_label != "Location pending" else ["Resource location is missing."],
            source_row_index=row_index,
            display_fields=self._resource_display_fields(resource),
            map_status=LocationConfidence.EXACT if (resource.current_geo or resource.location) else LocationConfidence.UNKNOWN,
        )

    def _questions_for_drafts(self, drafts: list[RecordDraft]) -> list[UserQuestion]:
        questions: list[UserQuestion] = []
        if any(
            draft.draft_type == DraftRecordType.INCIDENT
            and not draft.removed
            and draft.payload.get("location_confidence") == "UNKNOWN"
            for draft in drafts
        ):
            questions.append(
                UserQuestion(
                    question_id="location",
                    question="One or more incident locations are missing or ambiguous. Add an address or map pin before dispatch.",
                    field="location_text",
                )
            )
        return questions

    def _reevaluate_incident_draft(self, draft: RecordDraft, prompt: str) -> None:
        raw_input = draft.payload.get("raw_input", draft.title)
        reevaluation_input = self._prune_and_redact(f"{raw_input}\nOperator correction: {prompt}")
        result = self.extractor.extract_with_metadata(reevaluation_input)
        extraction = result.extraction
        draft.title = f"{extraction.category} - {extraction.location_text or 'Location pending'}"
        draft.payload.update(
            {
                "raw_input": reevaluation_input,
                "extracted": extraction.model_dump(mode="json"),
                "location_confidence": "UNKNOWN" if extraction.data_quality.missing_location else "APPROXIMATE",
                "operator_prompt": prompt,
                "provider_used": result.provider_used,
                "provider_fallbacks": result.provider_fallbacks,
                "parse_warnings": result.warnings,
                "schema_validated": result.schema_validated,
            }
        )
        draft.confidence = extraction.confidence
        draft.warnings = list(
            dict.fromkeys(
                [
                    *result.warnings,
                    *extraction.data_quality.needs_followup_questions,
                    f"Reevaluated with operator prompt: {prompt}",
                ]
            )
        )

    def _reevaluate_team_draft(self, draft: RecordDraft, prompt: str) -> None:
        row = self._stringify_values(draft.payload.get("source_row") or {})
        self._apply_prompt_patch_to_row(row, prompt, "teams")
        notes = str(row.get("notes") or draft.payload.get("raw_input") or "")
        row["notes"] = self._prune_and_redact(f"{notes}\nOperator correction: {prompt}")
        updated = self._team_draft_from_row(row, prompt)
        draft.title = updated.title
        draft.payload = updated.payload
        draft.confidence = min(1.0, updated.confidence + 0.03)
        draft.warnings = [*updated.warnings, f"Reevaluated with operator prompt: {prompt}"]

    def _reevaluate_resource_draft(self, draft: RecordDraft, prompt: str) -> None:
        row = self._stringify_values(draft.payload.get("source_row") or {})
        self._apply_prompt_patch_to_row(row, prompt, "resources")
        notes = str(row.get("notes") or draft.payload.get("raw_input") or "")
        row["notes"] = self._prune_and_redact(f"{notes}\nOperator correction: {prompt}")
        updated = self._resource_draft_from_row(row, prompt)
        draft.title = updated.title
        draft.payload = updated.payload
        draft.confidence = min(1.0, updated.confidence + 0.03)
        draft.warnings = [*updated.warnings, f"Reevaluated with operator prompt: {prompt}"]

    def _row_matches_target(self, row: dict[str, str], target: str) -> bool:
        keys = {key.strip().lower() for key, value in row.items() if str(value or "").strip()}
        incident_keys = {"raw_input", "description", "incident", "category", "location_text", "required_resources", "severity"}
        team_keys = {"team_id", "display_name", "name", "capability_tags", "skills", "capabilities", "base_label", "member_ids", "service_radius_km"}
        resource_keys = {"resource_id", "resource_type", "category", "quantity_available", "quantity", "location_label", "owning_team_id", "constraints"}
        if target == "teams":
            return bool(keys & team_keys)
        if target == "resources":
            return bool(keys & resource_keys)
        return bool(keys & incident_keys)

    def _apply_prompt_patch_to_row(self, row: dict[str, str], prompt: str, target: str) -> None:
        lowered = prompt.lower()
        if target == "teams":
            name = self._extract_prompt_value(prompt, ["name", "team name", "display name"])
            location = self._extract_prompt_value(prompt, ["location", "base", "base label"])
            capabilities = self._extract_prompt_value(prompt, ["capabilities", "capability", "skills"])
            radius = self._extract_prompt_number(prompt, ["radius", "service radius"])
            if name:
                row["display_name"] = name
            if location:
                row["base_label"] = location
            if capabilities:
                row["capability_tags"] = capabilities
            if radius is not None:
                row["service_radius_km"] = str(radius)
        elif target == "resources":
            resource_type = self._extract_prompt_value(prompt, ["resource type", "type", "name"])
            location = self._extract_prompt_value(prompt, ["location", "depot", "warehouse"])
            constraints = self._extract_prompt_value(prompt, ["constraints", "constraint"])
            quantity = self._extract_prompt_number(prompt, ["quantity", "stock", "count"])
            if resource_type:
                row["resource_type"] = resource_type
            if location:
                row["location_label"] = location
            if constraints:
                row["constraints"] = constraints
            if quantity is not None:
                row["quantity_available"] = str(quantity)

    def _extract_prompt_value(self, prompt: str, labels: list[str]) -> str | None:
        for label in labels:
            pattern = rf"{re.escape(label)}\s*(?:to|=|:)\s*([^.;\n]+)"
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_prompt_number(self, prompt: str, labels: list[str]) -> float | None:
        for label in labels:
            pattern = rf"{re.escape(label)}\s*(?:to|=|:)?\s*(-?\d+(?:\.\d+)?)"
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

    def _incident_display_fields(self, extraction: IncidentExtraction, geo: GeoPoint | None) -> dict[str, Any]:
        return {
            "category": extraction.category,
            "subcategory": extraction.subcategory,
            "urgency": extraction.urgency,
            "location_text": extraction.location_text,
            "people_affected": extraction.people_affected,
            "time_to_act_hours": extraction.time_to_act_hours,
            "resources": [item.model_dump(mode="json") for item in extraction.required_resources],
            "geo": geo.model_dump(mode="json") if geo else None,
        }

    def _team_display_fields(self, team: Team) -> dict[str, Any]:
        return {
            "team_id": team.team_id,
            "display_name": team.display_name,
            "capability_tags": team.capability_tags,
            "base_label": team.base_label,
            "availability_status": team.availability_status,
            "geo": (team.current_geo or team.base_geo).model_dump(mode="json") if (team.current_geo or team.base_geo) else None,
        }

    def _resource_display_fields(self, resource: ResourceInventory) -> dict[str, Any]:
        return {
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "quantity_available": resource.quantity_available,
            "location_label": resource.location_label,
            "owning_team_id": resource.owning_team_id,
            "geo": (resource.current_geo or resource.location).model_dump(mode="json") if (resource.current_geo or resource.location) else None,
        }

    def _apply_field_updates(self, draft: RecordDraft, updates: dict[str, Any]) -> list[str]:
        changed: list[str] = []
        for raw_path, value in updates.items():
            path = raw_path[8:] if raw_path.startswith("payload.") else raw_path
            if not path:
                continue
            self._set_path(draft.payload, path.split("."), value)
            changed.append(path)
        return changed

    def _set_path(self, target: dict[str, Any], parts: list[str], value: Any) -> None:
        current: dict[str, Any] = target
        for part in parts[:-1]:
            next_value = current.get(part)
            if not isinstance(next_value, dict):
                next_value = {}
                current[part] = next_value
            current = next_value
        current[parts[-1]] = value

    def _refresh_draft_display(self, draft: RecordDraft) -> None:
        try:
            if draft.draft_type == DraftRecordType.INCIDENT:
                extraction = IncidentExtraction.model_validate(draft.payload.get("extracted"))
                geo_payload = draft.payload.get("geo")
                geo = GeoPoint.model_validate(geo_payload) if isinstance(geo_payload, dict) else None
                draft.title = f"{extraction.category} - {extraction.location_text or 'Location pending'}"
                draft.display_fields = self._incident_display_fields(extraction, geo)
                draft.map_status = LocationConfidence.EXACT if geo else LocationConfidence(draft.payload.get("location_confidence", "UNKNOWN"))
            elif draft.draft_type == DraftRecordType.TEAM:
                team = Team.model_validate(draft.payload.get("team"))
                draft.title = f"{team.display_name} ({', '.join(team.capability_tags[:2])})"
                draft.display_fields = self._team_display_fields(team)
                draft.map_status = LocationConfidence.EXACT if (team.current_geo or team.base_geo) else LocationConfidence.UNKNOWN
            elif draft.draft_type == DraftRecordType.RESOURCE:
                resource = ResourceInventory.model_validate(draft.payload.get("resource"))
                draft.title = f"{resource.resource_type} ({resource.quantity_available:g} available)"
                draft.display_fields = self._resource_display_fields(resource)
                draft.map_status = LocationConfidence.EXACT if (resource.current_geo or resource.location) else LocationConfidence.UNKNOWN
        except Exception:
            draft.warnings = [*draft.warnings, "Draft display could not be refreshed after edits."]

    def _source_hash(self, record_type: str, raw: str) -> str:
        normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", f"{record_type}:{raw}".lower())).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _find_duplicate_case(self, raw_input: str, source_hash: str, org_id: str) -> Any | None:
        normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", raw_input.lower())).strip()
        for case in self.repository.list_cases():
            if case.org_id != org_id:
                continue
            if case.source_hash and case.source_hash == source_hash:
                return case
            existing = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", case.raw_input.lower())).strip()
            if existing == normalized:
                return case
        return None

    def _split_tags(self, value: str | None) -> list[str]:
        if not value:
            return []
        return [
            token.strip().upper().replace(" ", "_")
            for token in re.split(r"[,;/|]+", value)
            if token.strip()
        ]

    def _parse_float(self, value: str | None, default: float) -> float:
        if value is None or value == "":
            return default
        try:
            return float(value)
        except ValueError:
            return default

    def _geo_from_row(self, row: dict[str, str], prefix: str = "") -> GeoPoint | None:
        candidates: list[tuple[str, str]] = []
        if prefix:
            candidates.extend(
                [
                    (f"{prefix}_lat", f"{prefix}_lng"),
                    (f"{prefix}_latitude", f"{prefix}_longitude"),
                ]
            )
        else:
            candidates.extend(
                [
                    ("lat", "lng"),
                    ("latitude", "longitude"),
                    ("location_lat", "location_lng"),
                    ("location_latitude", "location_longitude"),
                ]
            )
        for lat_key, lng_key in candidates:
            lat_raw = row.get(lat_key)
            lng_raw = row.get(lng_key)
            if not lat_raw or not lng_raw:
                continue
            try:
                lat = float(lat_raw)
                lng = float(lng_raw)
            except ValueError:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            return GeoPoint(lat=lat, lng=lng)
        return None

    def _availability(self, value: str | None) -> AvailabilityStatus:
        normalized = (value or "AVAILABLE").strip().upper().replace("-", "_")
        if normalized in AvailabilityStatus.__members__:
            return AvailabilityStatus[normalized]
        if normalized in {item.value for item in AvailabilityStatus}:
            return AvailabilityStatus(normalized)
        return AvailabilityStatus.AVAILABLE

    def _stringify_values(self, value: dict[str, Any]) -> dict[str, str]:
        return {str(key): "" if item is None else str(item) for key, item in value.items()}

    def _require_run_org(self, run: GraphRun, actor: UserContext) -> None:
        if run.org_id != actor.active_org_id:
            raise PermissionError("Graph run belongs to another organization.")

    def _prune_and_redact(self, text: str) -> str:
        redacted = re.sub(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)", "[REDACTED_PHONE]", text)
        unique_lines: list[str] = []
        seen: set[str] = set()
        for line in redacted.splitlines():
            cleaned = " ".join(line.strip().split())
            if not cleaned or len(cleaned) < 3:
                continue
            normalized = cleaned.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_lines.append(cleaned)
        return "\n".join(unique_lines)[:12000]
