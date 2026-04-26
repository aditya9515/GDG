from __future__ import annotations

import asyncio
import csv
import io
import json
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
    BatchDispatchPlan,
    BatchPlanStatus,
    BatchPlanningRequest,
    BatchPlanningStats,
    BatchReplanRequest,
    CandidateGenerationResult,
    CategoryKind,
    CaseEvent,
    CaseRecord,
    CaseStatus,
    DraftRecordType,
    DuplicateCandidate,
    GeoPoint,
    GraphRun,
    GraphRunRequest,
    GraphRunStatus,
    IncidentExtraction,
    InfoTokenType,
    LocationConfidence,
    PlannedCaseAssignment,
    RecordDraft,
    Recommendation,
    ResourceDraftPayload,
    ResourceNeed,
    ResourceInventory,
    ReservePolicyMode,
    SourceArtifact,
    Team,
    TeamDraftPayload,
    UrgencyKind,
    UserContext,
    UserQuestion,
    VectorRecord,
)
from app.repositories.base import Repository
from app.services.duplicates import DuplicateService
from app.services.docling_parser import DoclingParserService
from app.services.extractor import ExtractionService
from app.services.geocoding import GeocodingService
from app.services.matching import MatchingService
from app.services.routing import RoutingService
from app.services.scoring import ScoringService
from app.services.tokens import TokenService
from app.services.vectors import VectorService


MAX_ARTIFACT_TEXT_CHARS = 2_000
MAX_ARTIFACT_JSON_STRING_CHARS = 600
MAX_DRAFT_TEXT_CHARS = 140
MAX_SOURCE_FRAGMENT_CHARS = 100
MAX_ROW_VALUE_CHARS = 45
MAX_WARNING_CHARS = 220
MAX_WARNINGS_PER_DRAFT = 8
MAX_DUPLICATE_CANDIDATES = 3


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
    teams: list[Team]
    volunteers: list[Any]
    resources: list[ResourceInventory]
    recommendations: list[Any]
    reserve_recommendations: list[Any]
    conflicts: list[str]
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
        geocoder: GeocodingService,
        routing: RoutingService,
        duplicate_service: DuplicateService,
    ) -> None:
        self.repository = repository
        self.docling = docling
        self.extractor = extractor
        self.scorer = scorer
        self.matcher = matcher
        self.token_service = token_service
        self.vector_service = vector_service
        self.geocoder = geocoder
        self.routing = routing
        self.duplicate_service = duplicate_service
        self.source_graph = None
        self.dispatch_graph = self._compile_dispatch_graph()

    def run_graph1(self, payload: GraphRunRequest, actor: UserContext) -> GraphRun:
        org_id = actor.active_org_id or "unassigned"
        parsed = self.docling.parse_text(payload.text or "", payload.source_kind)
        cleaned = self._prune_and_redact(parsed.markdown or payload.text or "")
        artifact = SourceArtifact(
            artifact_id=f"art-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            source_kind=payload.source_kind,
            filename=None,
            text=cleaned[:12000],
            docling_markdown=cleaned,
            docling_json=parsed.structured,
            parse_status="COMPLETED",
            parse_warnings=parsed.warnings,
            detected_languages=parsed.detected_languages,
            ocr_used=parsed.ocr_used,
        )
        batch_result = self.extractor.extract_document_batch_with_metadata(cleaned, "manual_text")
        drafts = self._drafts_from_document_batch(batch_result.batch, payload.operator_prompt, cleaned, payload.target, batch_result)
        drafts = self._enrich_drafts_with_geocodes(drafts)
        drafts = self._enrich_drafts_with_duplicates(drafts, org_id)
        warnings = [*parsed.warnings, *batch_result.warnings, *batch_result.batch.warnings]
        if not drafts:
            warnings.append("No matching data found for this target.")
        artifact.parse_warnings = list(dict.fromkeys(warnings))
        run = GraphRun(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            graph_name="source_to_operational_records_graph",
            status=GraphRunStatus.WAITING_FOR_CONFIRMATION,
            created_by=actor.uid,
            source_artifacts=[artifact],
            drafts=drafts,
            user_questions=self._questions_for_drafts(drafts),
            needs_user_input=False,
            next_action="confirm_or_edit",
            meta=self._run_meta(drafts, warnings),
        )
        return self._save_graph_run(run)

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
            batch_result = self.extractor.extract_document_batch_with_metadata(text, filename)
            warnings.extend(batch_result.warnings)
            warnings.extend(batch_result.batch.warnings)
            drafts = self._drafts_from_document_batch(batch_result.batch, operator_prompt, text, target, batch_result)

        drafts = self._enrich_drafts_with_geocodes(drafts)
        drafts = self._enrich_drafts_with_duplicates(drafts, org_id)
        if not drafts:
            warnings.append("No matching data found for this target.")

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
            meta=self._run_meta(drafts, warnings),
        )
        return self._save_graph_run(run)

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
        return {"run": self._save_graph_run(run)}

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
        if (case.geo is None and not case.location_text) or (case.location_confidence == "UNKNOWN" and not case.location_text):
            questions.append(
                UserQuestion(
                    question_id="confirm_location",
                    question="Incident location is missing or ambiguous. Provide an exact address or map pin.",
                    field="location_text",
                )
            )
        teams = [team for team in self.repository.list_teams() if team.org_id == org_id]
        resources = [resource for resource in self.repository.list_resources() if resource.org_id == org_id]
        if not teams:
            questions.append(
                UserQuestion(
                    question_id="team_data",
                    question="No teams are available in this organization. Import or create teams before dispatch.",
                    field="teams",
                )
            )
        if case.extracted_json and case.extracted_json.required_resources and not resources:
            questions.append(
                UserQuestion(
                    question_id="resource_data",
                    question="No resource inventory is available for this organization. Import or create resources before dispatch.",
                    field="resources",
                    required=False,
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
        result = self.matcher.generate_candidates_for_case(case, teams, volunteers, resources)
        return {
            "teams": teams,
            "volunteers": volunteers,
            "resources": resources,
            "recommendations": result.recommendations,
            "reserve_recommendations": result.reserve_recommendations,
            "conflicts": result.conflicts,
            "unassigned_reason": result.unassigned_reason,
        }

    def _graph2_maps_eta_node(self, state: AgentGraphState) -> AgentGraphState:
        case = state["case"]
        teams_by_id = {team.team_id: team for team in state.get("teams", [])}
        enriched: list[Any] = []
        reserves: list[Any] = []
        for group, output in ((state.get("recommendations", []), enriched), (state.get("reserve_recommendations", []), reserves)):
            for recommendation in group:
                if recommendation.team_id and recommendation.team_id in teams_by_id:
                    team = teams_by_id[recommendation.team_id]
                    try:
                        route = self.routing.route_sync(team.current_geo or team.base_geo, case.geo)
                        recommendation.route_summary = route
                        recommendation.eta_minutes = route.duration_minutes
                    except Exception:
                        pass
                output.append(recommendation)
        return {"recommendations": enriched, "reserve_recommendations": reserves}

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
            return {"run": self._save_graph_run(run)}
        case = state["case"]
        recommendations = state.get("recommendations", [])
        reserve_recommendations = state.get("reserve_recommendations", [])
        conflicts = state.get("conflicts", [])
        reason = state.get("unassigned_reason")
        draft = RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.DISPATCH,
            title=f"Dispatch plan for {case.case_id}",
            payload={
                "case_id": case.case_id,
                "recommendations": [item.model_dump(mode="json") for item in recommendations],
                "ranked_recommendations": [item.model_dump(mode="json") for item in recommendations],
                "selected_plan": recommendations[0].model_dump(mode="json") if recommendations else None,
                "reserve_teams": [item.model_dump(mode="json") for item in reserve_recommendations],
                "conflicts": conflicts,
                "reasoning_summary": self._dispatch_reasoning_summary(recommendations, reserve_recommendations, conflicts, reason),
                "unassigned_reason": reason,
                "context_records": [item.record_id for item in state.get("context_records", [])],
                "used_context_records": [item.record_id for item in state.get("context_records", [])],
            },
            confidence=0.8 if recommendations else 0.35,
            warnings=conflicts if recommendations else [reason or "No feasible dispatch option found.", *conflicts],
        )
        run = GraphRun(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            org_id=org_id,
            graph_name="dispatch_assignment_graph",
            status=GraphRunStatus.WAITING_FOR_CONFIRMATION,
            created_by=actor.uid,
            drafts=[draft],
            next_action="confirm_or_edit",
            meta={
                "recommendation_count": len(recommendations),
                "reserve_count": len(reserve_recommendations),
                "conflict_count": len(conflicts),
            },
        )
        return {"run": self._save_graph_run(run)}

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
                before_payload = self._json_safe(draft.payload)
                draft.frozen = True
                changed_fields: list[str] = []
                if prompt.strip():
                    model_changed_fields = self._apply_full_context_draft_reevaluation(run, draft, prompt, actor)
                    if model_changed_fields is None:
                        if draft.draft_type == DraftRecordType.INCIDENT:
                            self._reevaluate_incident_draft(draft, prompt)
                        elif draft.draft_type == DraftRecordType.TEAM:
                            self._reevaluate_team_draft(draft, prompt)
                        elif draft.draft_type == DraftRecordType.RESOURCE:
                            self._reevaluate_resource_draft(draft, prompt)
                        elif draft.draft_type == DraftRecordType.DISPATCH:
                            self._reevaluate_dispatch_draft(draft, prompt)
                        else:
                            draft.payload["operator_prompt"] = prompt
                            draft.warnings = [*draft.warnings, f"Reevaluated with operator prompt: {prompt}"]
                            draft.confidence = min(1.0, draft.confidence + 0.03)
                        changed_fields.append("operator_prompt")
                    else:
                        changed_fields.extend(["operator_prompt", *model_changed_fields])
                changed_fields.extend(self._apply_prompt_patch_to_draft(draft, prompt))
                changed_fields.extend(self._apply_field_updates(draft, field_updates or {}))
                self._clear_stale_geos_after_location_edits(draft, before_payload)
                draft.changed_fields = list(dict.fromkeys([*draft.changed_fields, *changed_fields]))
                self._refresh_draft_display(draft)
                self._enrich_drafts_with_geocodes([draft])
                after_payload = self._json_safe(draft.payload)
                draft.changed_fields = list(
                    dict.fromkeys(
                        [
                            *draft.changed_fields,
                            *changed_fields,
                            *self._changed_payload_paths(before_payload, after_payload),
                        ]
                    )
                )
                draft.frozen = False
        run.status = GraphRunStatus.WAITING_FOR_CONFIRMATION
        run.next_action = "confirm_or_edit"
        return self._save_graph_run(run)

    def remove_draft(self, run_id: str, draft_id: str, reason: str | None, actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        for draft in run.drafts:
            if draft.draft_id == draft_id:
                draft.removed = True
                draft.warnings = [*draft.warnings, f"Removed before commit: {reason or 'operator request'}"]
        return self._save_graph_run(run)

    def confirm_graph1(self, run_id: str, actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        for draft in run.drafts:
            if draft.removed:
                continue
            if draft.draft_type == DraftRecordType.INCIDENT:
                run.committed_record_ids.append(self._commit_incident_draft(run, draft, actor))
            elif draft.draft_type == DraftRecordType.TEAM:
                run.committed_record_ids.append(self._commit_team_draft(run, draft, actor))
            elif draft.draft_type == DraftRecordType.RESOURCE:
                run.committed_record_ids.append(self._commit_resource_draft(run, draft, actor))
        run.status = GraphRunStatus.COMMITTED
        run.next_action = "complete"
        run.meta = {**run.meta, **self._run_meta(run.drafts), "committed_count": len(run.committed_record_ids)}
        return self._save_graph_run(run)

    def _commit_incident_draft(self, run: GraphRun, draft: RecordDraft, actor: UserContext) -> str:
        raw_input = str(draft.payload.get("source_raw_input") or draft.payload.get("raw_input") or draft.title)
        source_hash = self.duplicate_service.source_hash("INCIDENT", raw_input)
        duplicate = self.duplicate_service.find_exact_duplicate("INCIDENT", raw_input, run.org_id, self.repository.list_cases())
        if duplicate is not None:
            draft.warnings = [*draft.warnings, f"Duplicate incident detected; reused {duplicate.case_id}."]
            return duplicate.case_id

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
                    LocationConfidence(draft.payload.get("location_confidence", "EXACT")),
                )
        if extraction.confidence >= 0.4:
            rationale = self.scorer.score(extraction)
            case = self.repository.save_scoring(case.case_id, rationale.final_score, rationale, rationale.final_urgency)
        tokens = self.token_service.from_incident(case, extraction)
        self.repository.save_info_tokens(case.case_id, tokens)
        self._index_incident(run, case, extraction, tokens[0].token_id if tokens else None, actor)
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
        return case.case_id

    def _commit_team_draft(self, run: GraphRun, draft: RecordDraft, actor: UserContext) -> str:
        team = Team.model_validate(draft.payload["team"])
        team.org_id = run.org_id
        duplicate = self._find_duplicate_team(team, run.org_id)
        if duplicate is not None:
            draft.warnings = [*draft.warnings, f"Duplicate team detected; reused {duplicate.team_id}."]
            return duplicate.team_id
        if not (team.current_geo or team.base_geo) and team.base_label and team.base_label != "Location pending":
            geo = self.geocoder.geocode_sync(team.base_label)
            if geo is not None:
                team.base_geo = geo
                team.current_geo = team.current_geo or geo
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
        self._index_team(run, team, tokens[0].token_id if tokens else None, actor)
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
        return team.team_id

    def _commit_resource_draft(self, run: GraphRun, draft: RecordDraft, actor: UserContext) -> str:
        resource = ResourceInventory.model_validate(draft.payload["resource"])
        resource.org_id = run.org_id
        duplicate = self._find_duplicate_resource(resource, run.org_id)
        if duplicate is not None:
            draft.warnings = [*draft.warnings, f"Duplicate resource detected; reused {duplicate.resource_id}."]
            return duplicate.resource_id
        if not (resource.current_geo or resource.location) and resource.location_label and resource.location_label != "Location pending":
            geo = self.geocoder.geocode_sync(resource.location_label)
            if geo is not None:
                resource.location = geo
                resource.current_geo = resource.current_geo or geo
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
        self._index_resource(run, resource, tokens[0].token_id if tokens else None, actor)
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
        return resource.resource_id

    def _index_incident(self, run: GraphRun, case: CaseRecord, extraction: IncidentExtraction, token_id: str | None, actor: UserContext) -> None:
        text = self.vector_service.build_incident_embedding_text(case, extraction)
        self.repository.save_vector_records(
            [
                VectorRecord(
                    vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                    org_id=run.org_id,
                    record_type="INCIDENT",
                    record_id=case.case_id,
                    token_id=token_id,
                    embedding=self.vector_service.embed(text),
                    text=text,
                    metadata={"category": extraction.category, "urgency": extraction.urgency},
                    source_refs=[artifact.artifact_id for artifact in run.source_artifacts],
                    created_by=actor.uid,
                )
            ]
        )

    def _index_team(self, run: GraphRun, team: Team, token_id: str | None, actor: UserContext) -> None:
        text = self.vector_service.build_team_embedding_text(team)
        self.repository.save_vector_records(
            [
                VectorRecord(
                    vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                    org_id=run.org_id,
                    record_type="TEAM",
                    record_id=team.team_id,
                    token_id=token_id,
                    embedding=self.vector_service.embed(text),
                    text=text,
                    metadata={"capabilities": team.capability_tags, "availability": team.availability_status.value},
                    source_refs=[artifact.artifact_id for artifact in run.source_artifacts],
                    created_by=actor.uid,
                )
            ]
        )

    def _index_resource(self, run: GraphRun, resource: ResourceInventory, token_id: str | None, actor: UserContext) -> None:
        text = self.vector_service.build_resource_embedding_text(resource)
        self.repository.save_vector_records(
            [
                VectorRecord(
                    vector_id=f"vec-{uuid.uuid4().hex[:10]}",
                    org_id=run.org_id,
                    record_type="RESOURCE",
                    record_id=resource.resource_id,
                    token_id=token_id,
                    embedding=self.vector_service.embed(text),
                    text=text,
                    metadata={"resource_type": resource.resource_type, "quantity_available": resource.quantity_available},
                    source_refs=[artifact.artifact_id for artifact in run.source_artifacts],
                    created_by=actor.uid,
                )
            ]
        )

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
                geo = self.geocoder.geocode_sync(location_answer)
                self.repository.update_case_location(
                    case_id,
                    location_answer,
                    geo.lat if geo is not None else None,
                    geo.lng if geo is not None else None,
                    LocationConfidence.APPROXIMATE if geo is not None else LocationConfidence.UNKNOWN,
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
        return self._save_graph_run(run)

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
                return self._save_graph_run(run)
            top = recommendations[0]
            selected = draft.payload.get("selected_plan")
            if isinstance(selected, dict):
                top = selected
            reserve_team_ids = [
                item.get("team_id")
                for item in draft.payload.get("reserve_teams", [])
                if isinstance(item, dict) and item.get("team_id")
            ]
            assignment = AssignmentDecision(
                assignment_id=f"asg-{uuid.uuid4().hex[:10]}",
                org_id=run.org_id,
                case_id=top.get("case_id") or draft.payload.get("case_id"),
                incident_id=draft.payload.get("case_id"),
                team_id=top.get("team_id"),
                volunteer_ids=top.get("volunteer_ids", []),
                resource_ids=top.get("resource_ids", []),
                resource_allocations=top.get("resource_allocations", []),
                reserve_team_ids=reserve_team_ids,
                match_score=top.get("match_score", 0.5),
                eta_minutes=top.get("eta_minutes"),
                route_summary=top.get("route_summary"),
                confirmed_by=actor.uid,
            )
            self.repository.create_assignment(assignment)
            run.committed_record_ids.append(assignment.assignment_id)
        run.status = GraphRunStatus.COMMITTED
        run.next_action = "complete"
        return self._save_graph_run(run)

    def run_graph2_batch(self, payload: BatchPlanningRequest, actor: UserContext) -> GraphRun:
        run = self._build_graph2_batch_run(payload, actor)
        return self._save_graph_run(run)

    def edit_batch_case_plan(
        self,
        run_id: str,
        case_id: str,
        actor: UserContext,
        prompt: str | None = None,
        field_updates: dict[str, Any] | None = None,
    ) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        draft, plan = self._batch_plan_from_run(run)
        field_updates = field_updates or {}
        target = next((item for item in plan.planned_cases if item.case_id == case_id), None)
        if target is None:
            raise KeyError(case_id)

        lowered = (prompt or "").lower()
        if prompt:
            self._apply_full_context_batch_case_reevaluation(run, draft, plan, target, prompt, actor)

        if prompt:
            target.operator_note = prompt
            target.reasons = [*target.reasons, f"Operator note: {prompt}"]

        selected_team = target.selected_recommendation.team_id if target.selected_recommendation else None
        if selected_team and any(token in lowered for token in ("exclude", "avoid", "do not use", "don't use")) and selected_team.lower() in lowered:
            replacement = next(
                (
                    item
                    for item in target.alternative_recommendations
                    if item.team_id and item.team_id != selected_team
                ),
                None,
            )
            if replacement is not None:
                target.selected_recommendation = replacement
                target.assignment_status = BatchPlanStatus.ASSIGNED
                target.reasons = [*target.reasons, f"Excluded {selected_team}; selected {replacement.team_id} instead."]
                target.conflict_flags = [*target.conflict_flags, f"Operator excluded {selected_team}."]
            else:
                target.selected_recommendation = None
                target.assignment_status = BatchPlanStatus.WAITING
                target.reasons = [*target.reasons, f"Excluded {selected_team}; no unused alternative was available."]
                target.conflict_flags = [*target.conflict_flags, f"No alternative after excluding {selected_team}."]

        if "waiting" in lowered or "defer" in lowered:
            target.assignment_status = BatchPlanStatus.WAITING
            target.reasons = [*target.reasons, "Operator moved this case to waiting."]

        if "promote" in lowered or "top priority" in lowered:
            target.planning_priority_score = min(1.0, target.planning_priority_score + 0.1)
            target.reasons = [*target.reasons, "Operator promoted this case priority for this run."]

        if field_updates:
            status = field_updates.get("assignment_status")
            if status:
                target.assignment_status = BatchPlanStatus(str(status))
            selected = field_updates.get("selected_recommendation")
            if isinstance(selected, dict):
                target.selected_recommendation = Recommendation.model_validate(selected)
            note = field_updates.get("operator_note")
            if note is not None:
                target.operator_note = str(note)

        plan.planned_cases = [
            target if item.case_id == case_id else item
            for item in plan.planned_cases
        ]
        plan.planned_cases.sort(key=lambda item: (-item.planning_priority_score, item.priority_rank, item.case_id))
        for index, item in enumerate(plan.planned_cases, start=1):
            item.priority_rank = index
        self._refresh_batch_plan_summary(plan)
        draft.payload["batch_plan"] = plan.model_dump(mode="json")
        draft.changed_fields = list(dict.fromkeys([*draft.changed_fields, f"case:{case_id}"]))
        draft.warnings = list(dict.fromkeys([*draft.warnings, f"Edited batch case plan for {case_id}."]))
        run.meta.update(plan.stats.model_dump(mode="json"))
        run.updated_at = self._now()
        return self._save_graph_run(run)

    def _apply_full_context_batch_case_reevaluation(
        self,
        run: GraphRun,
        draft: RecordDraft,
        plan: BatchDispatchPlan,
        target: PlannedCaseAssignment,
        prompt: str,
        actor: UserContext,
    ) -> list[str]:
        try:
            case = self.repository.get_case(target.case_id)
        except Exception:
            case = None
        envelope = self._reevaluation_envelope(
            run,
            draft,
            prompt,
            actor,
            extra={
                "reevaluation_scope": "batch_case_plan",
                "selected_planned_case": target.model_dump(mode="json"),
                "selected_case_record": case.model_dump(mode="json") if case is not None else None,
                "batch_plan_summary": {
                    "planned_case_count": len(plan.planned_cases),
                    "reserve_pool_team_ids": plan.reserve_pool_team_ids,
                    "reserve_pool_resource_ids": plan.reserve_pool_resource_ids,
                    "stats": plan.stats.model_dump(mode="json"),
                },
                "allowed_patch_shapes": {
                    "selected_case": "Patch fields on this planned case only.",
                    "case_location_override": "Optional location_text and/or geo {lat,lng}; routes will be recomputed by backend.",
                    "operator_note": "Short operator-facing note.",
                },
            },
        )
        result = self.extractor.reevaluate_payload_patch_with_metadata(envelope)
        patch = result.patch
        payload_patch = self._unwrap_payload_patch(patch.payload_patch)
        if result.provider_used == "Heuristic" or not payload_patch:
            return []
        changed: list[str] = []
        selected_patch = self._extract_selected_case_patch(payload_patch)
        if selected_patch:
            current = target.model_dump(mode="json")
            self._merge_payload_patch(current, selected_patch)
            updated = PlannedCaseAssignment.model_validate(current)
            for field_name in updated.model_fields:
                setattr(target, field_name, getattr(updated, field_name))
            changed.extend([f"case:{target.case_id}:{item}" for item in patch.changed_fields or selected_patch.keys()])

        override = self._extract_case_location_override(payload_patch, target.case_id)
        if override:
            overrides = draft.payload.setdefault("case_overrides", {})
            if isinstance(overrides, dict):
                existing = overrides.get(target.case_id) if isinstance(overrides.get(target.case_id), dict) else {}
                next_override = dict(existing)
                self._merge_payload_patch(next_override, override)
                self._geocode_case_override(next_override)
                overrides[target.case_id] = next_override
                self._recompute_batch_case_routes(run, target, next_override)
                changed.append(f"case:{target.case_id}:location_override")

        if patch.reasoning_summary:
            target.reasons = list(dict.fromkeys([*target.reasons, patch.reasoning_summary]))
        if patch.warnings or result.warnings:
            target.conflict_flags = list(dict.fromkeys([*target.conflict_flags, *result.warnings, *patch.warnings]))
        return changed

    def _extract_selected_case_patch(self, payload_patch: dict[str, Any]) -> dict[str, Any]:
        for key in ("selected_case", "planned_case", "target_case", "planned_case_patch"):
            value = payload_patch.get(key)
            if isinstance(value, dict):
                return value
        planned_fields = set(PlannedCaseAssignment.model_fields)
        return {key: value for key, value in payload_patch.items() if key in planned_fields}

    def _extract_case_location_override(self, payload_patch: dict[str, Any], case_id: str) -> dict[str, Any]:
        for key in ("case_location_override", "location_override", "case_geo_override"):
            value = payload_patch.get(key)
            if isinstance(value, dict):
                return value
        overrides = payload_patch.get("case_overrides")
        if isinstance(overrides, dict):
            value = overrides.get(case_id)
            if isinstance(value, dict):
                return value
        selected = payload_patch.get("selected_case")
        if isinstance(selected, dict):
            for key in ("case_location_override", "location_override"):
                value = selected.get(key)
                if isinstance(value, dict):
                    return value
        return {}

    def _geocode_case_override(self, override: dict[str, Any]) -> None:
        geo_payload = override.get("geo") or override.get("location")
        if isinstance(geo_payload, dict):
            try:
                override["geo"] = GeoPoint.model_validate(geo_payload).model_dump(mode="json")
                return
            except Exception:
                pass
        lat = override.get("lat")
        lng = override.get("lng")
        if isinstance(lat, int | float) and isinstance(lng, int | float):
            override["geo"] = GeoPoint(lat=float(lat), lng=float(lng)).model_dump(mode="json")
            return
        location_text = override.get("location_text") or override.get("address")
        if isinstance(location_text, str) and location_text.strip():
            geo = self.geocoder.geocode_sync(location_text)
            if geo is not None:
                override["geo"] = geo.model_dump(mode="json")

    def _recompute_batch_case_routes(
        self,
        run: GraphRun,
        target: PlannedCaseAssignment,
        override: dict[str, Any] | None = None,
    ) -> None:
        destination: GeoPoint | None = None
        if override and isinstance(override.get("geo"), dict):
            try:
                destination = GeoPoint.model_validate(override["geo"])
            except Exception:
                destination = None
        if destination is None:
            try:
                destination = self.repository.get_case(target.case_id).geo
            except Exception:
                destination = None
        team_map = {team.team_id: team for team in self.repository.list_teams() if team.org_id == run.org_id}

        def refresh(recommendation: Recommendation | None) -> None:
            if recommendation is None or not recommendation.team_id:
                return
            team = team_map.get(recommendation.team_id)
            origin = (team.current_geo or team.base_geo) if team else None
            try:
                route = self.routing.route_sync(origin, destination)
            except Exception:
                return
            recommendation.route_summary = route
            recommendation.eta_minutes = route.duration_minutes

        refresh(target.selected_recommendation)
        for recommendation in target.alternative_recommendations:
            refresh(recommendation)
        for recommendation in target.reserve_recommendations:
            refresh(recommendation)

    def replan_graph2_batch(self, run_id: str, payload: BatchReplanRequest, actor: UserContext) -> GraphRun:
        existing = self.repository.get_graph_run(run_id)
        self._require_run_org(existing, actor)
        request_payload = dict(existing.meta.get("request") or {})
        if payload.operator_prompt is not None:
            request_payload["operator_prompt"] = payload.operator_prompt
        if payload.reserve_policy is not None:
            request_payload["reserve_policy"] = payload.reserve_policy.model_dump(mode="json")
        request = BatchPlanningRequest.model_validate(request_payload or {})
        rerun = self._build_graph2_batch_run(request, actor)
        rerun.run_id = existing.run_id
        rerun.created_at = existing.created_at
        rerun.committed_record_ids = list(existing.committed_record_ids)
        rerun.meta["replanned_from"] = existing.run_id
        return self.repository.save_graph_run(rerun)

    def confirm_graph2_batch(self, run_id: str, actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        _, plan = self._batch_plan_from_run(run)
        existing_case_ids = {
            assignment.case_id
            for assignment in self.repository.list_assignments()
            if assignment.org_id == run.org_id
        }
        for planned in plan.planned_cases:
            if planned.assignment_status not in {BatchPlanStatus.ASSIGNED, BatchPlanStatus.PARTIAL}:
                continue
            if planned.case_id in existing_case_ids:
                continue
            assignment = self._assignment_from_planned_case(planned, plan, run, actor)
            if assignment is None:
                continue
            self.repository.create_assignment(assignment)
            run.committed_record_ids.append(assignment.assignment_id)
            existing_case_ids.add(planned.case_id)
        run.status = GraphRunStatus.COMMITTED
        run.next_action = "complete"
        run.updated_at = self._now()
        return self._save_graph_run(run)

    def confirm_graph2_batch_case(self, run_id: str, case_id: str, actor: UserContext) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        _, plan = self._batch_plan_from_run(run)
        planned = next((item for item in plan.planned_cases if item.case_id == case_id), None)
        if planned is None:
            raise KeyError(case_id)
        if planned.assignment_status not in {BatchPlanStatus.ASSIGNED, BatchPlanStatus.PARTIAL}:
            planned.reasons = [*planned.reasons, "Cannot confirm because this case is not assigned or partial."]
            run.status = GraphRunStatus.WAITING_FOR_USER
            return self._save_graph_run(run)
        existing = next(
            (
                item
                for item in self.repository.list_assignments()
                if item.org_id == run.org_id and item.case_id == case_id
            ),
            None,
        )
        if existing is None:
            assignment = self._assignment_from_planned_case(planned, plan, run, actor)
            if assignment is not None:
                self.repository.create_assignment(assignment)
                run.committed_record_ids.append(assignment.assignment_id)
                planned.reasons = [*planned.reasons, f"Committed staged dispatch {assignment.assignment_id}."]
        self._refresh_batch_plan_summary(plan)
        run.drafts[0].payload["batch_plan"] = plan.model_dump(mode="json")
        run.updated_at = self._now()
        return self._save_graph_run(run)

    def _build_graph2_batch_run(self, payload: BatchPlanningRequest, actor: UserContext) -> GraphRun:
        state: dict[str, Any] = {"payload": payload, "actor": actor}
        state.update(self._batch_load_open_cases_node(state))
        state.update(self._batch_score_and_rank_cases_node(state))
        state.update(self._batch_fetch_operational_assets_node(state))
        state.update(self._batch_build_feasible_candidates_node(state))
        state.update(self._batch_maps_eta_enrichment_node(state))
        state.update(self._batch_global_allocator_node(state))
        state.update(self._batch_reserve_allocator_node(state))
        state.update(self._batch_leftover_case_reasoner_node(state))
        return self._batch_preview_node(state)["run"]

    def _batch_load_open_cases_node(self, state: dict[str, Any]) -> dict[str, Any]:
        payload: BatchPlanningRequest = state["payload"]
        actor: UserContext = state["actor"]
        org_id = actor.active_org_id or "unassigned"
        cases = [case for case in self.repository.list_cases() if case.org_id == org_id]
        if payload.case_ids:
            selected = set(payload.case_ids)
            cases = [case for case in cases if case.case_id in selected]
        else:
            allowed = set(payload.filters.status) or {
                CaseStatus.NEW,
                CaseStatus.EXTRACTED,
                CaseStatus.SCORED,
                CaseStatus.NEEDS_REVIEW,
            }
            cases = [
                case
                for case in cases
                if case.status in allowed
                and case.status not in {CaseStatus.MERGED, CaseStatus.CLOSED, CaseStatus.ASSIGNED}
                and not case.final_dispatch_id
            ]
        if payload.filters.urgency:
            urgency_filter = set(payload.filters.urgency)
            cases = [case for case in cases if case.urgency in urgency_filter]
        return {"cases": cases}

    def _batch_score_and_rank_cases_node(self, state: dict[str, Any]) -> dict[str, Any]:
        cases: list[CaseRecord] = state.get("cases", [])
        payload: BatchPlanningRequest = state["payload"]
        actor: UserContext = state["actor"]
        resources = [item for item in self.repository.list_resources() if item.org_id == actor.active_org_id]
        planning_scores: dict[str, float] = {}
        refreshed_cases: list[CaseRecord] = []
        for case in cases:
            if case.extracted_json is not None and case.priority_score is None:
                rationale = self.scorer.score(case.extracted_json)
                case = self.repository.save_scoring(case.case_id, rationale.final_score, rationale, rationale.final_urgency)
            planning_scores[case.case_id] = self._planning_priority_score(case, resources, payload.operator_prompt)
            refreshed_cases.append(case)
        ranked = sorted(
            refreshed_cases,
            key=lambda item: (
                planning_scores.get(item.case_id, 0),
                item.priority_score or 0,
                item.created_at,
                item.case_id,
            ),
            reverse=True,
        )
        return {"ranked_cases": ranked, "planning_scores": planning_scores}

    def _batch_fetch_operational_assets_node(self, state: dict[str, Any]) -> dict[str, Any]:
        org_id = state["actor"].active_org_id
        teams = [item for item in self.repository.list_teams() if item.org_id == org_id]
        volunteers = [item for item in self.repository.list_volunteers() if item.org_id == org_id]
        resources = [item for item in self.repository.list_resources() if item.org_id == org_id]
        assignments = [item for item in self.repository.list_assignments() if item.org_id == org_id]
        return {"teams": teams, "volunteers": volunteers, "resources": resources, "assignments": assignments}

    def _batch_build_feasible_candidates_node(self, state: dict[str, Any]) -> dict[str, Any]:
        candidate_map: dict[str, CandidateGenerationResult] = {}
        for case in state.get("ranked_cases", []):
            candidate_map[case.case_id] = self.matcher.generate_candidates_for_case(
                case,
                state.get("teams", []),
                state.get("volunteers", []),
                state.get("resources", []),
                max_results=5 if case.urgency == UrgencyKind.CRITICAL else 3,
            )
        return {"candidate_map": candidate_map}

    def _batch_maps_eta_enrichment_node(self, state: dict[str, Any]) -> dict[str, Any]:
        teams_by_id = {team.team_id: team for team in state.get("teams", [])}
        candidate_map: dict[str, CandidateGenerationResult] = state.get("candidate_map", {})
        cases_by_id = {case.case_id: case for case in state.get("ranked_cases", [])}
        for case_id, result in candidate_map.items():
            case = cases_by_id.get(case_id)
            if case is None:
                continue
            route_limit = 5 if case.urgency == UrgencyKind.CRITICAL else 3
            for recommendation in result.recommendations[:route_limit]:
                team = teams_by_id.get(recommendation.team_id or "")
                if team is None:
                    continue
                try:
                    route = self.routing.route_sync(team.current_geo or team.base_geo, case.geo)
                    recommendation.route_summary = route
                    recommendation.eta_minutes = route.duration_minutes
                except Exception:
                    continue
            for recommendation in result.reserve_recommendations[:2]:
                team = teams_by_id.get(recommendation.team_id or "")
                if team is None:
                    continue
                try:
                    route = self.routing.route_sync(team.current_geo or team.base_geo, case.geo)
                    recommendation.route_summary = route
                    recommendation.eta_minutes = route.duration_minutes
                except Exception:
                    continue
        return {"candidate_map": candidate_map}

    def _batch_global_allocator_node(self, state: dict[str, Any]) -> dict[str, Any]:
        ranked_cases: list[CaseRecord] = state.get("ranked_cases", [])
        candidate_map: dict[str, CandidateGenerationResult] = state.get("candidate_map", {})
        planning_scores: dict[str, float] = state.get("planning_scores", {})
        resources: list[ResourceInventory] = state.get("resources", [])
        remaining_by_type = self._resource_quantities_by_type(resources)
        used_team_ids: set[str] = set()
        used_volunteer_ids: set[str] = set()
        used_resource_ids: set[str] = set()
        planned_cases: list[PlannedCaseAssignment] = []

        for rank, case in enumerate(ranked_cases, start=1):
            result = candidate_map.get(case.case_id) or CandidateGenerationResult()
            base_kwargs = {
                "case_id": case.case_id,
                "priority_rank": rank,
                "priority_score": float(case.priority_score or 0),
                "planning_priority_score": planning_scores.get(case.case_id, 0),
                "alternative_recommendations": result.recommendations[:5],
                "reserve_recommendations": result.reserve_recommendations,
                "conflict_flags": list(result.conflicts),
            }
            if case.extracted_json is None:
                planned_cases.append(
                    PlannedCaseAssignment(
                        **base_kwargs,
                        assignment_status=BatchPlanStatus.BLOCKED,
                        reasons=["Incident has not been extracted yet."],
                        unmet_requirements=["structured extraction"],
                    )
                )
                continue
            if case.geo is None or case.location_confidence == LocationConfidence.UNKNOWN:
                planned_cases.append(
                    PlannedCaseAssignment(
                        **base_kwargs,
                        assignment_status=BatchPlanStatus.BLOCKED,
                        reasons=["Missing or ambiguous location prevents route-aware dispatch."],
                        unmet_requirements=["exact incident location"],
                    )
                )
                continue
            if not result.recommendations:
                planned_cases.append(
                    PlannedCaseAssignment(
                        **base_kwargs,
                        assignment_status=BatchPlanStatus.UNASSIGNED,
                        reasons=[result.unassigned_reason or "No feasible team/resource option exists."],
                        unmet_requirements=self._unmet_requirements(case, None, remaining_by_type),
                    )
                )
                continue

            selected = next(
                (
                    recommendation
                    for recommendation in result.recommendations
                    if self._recommendation_available(
                        recommendation,
                        used_team_ids,
                        used_volunteer_ids,
                        remaining_by_type,
                        require_resources=True,
                        case=case,
                    )
                ),
                None,
            )
            if selected is not None:
                selected = selected.model_copy(deep=True)
                self._consume_recommendation(selected, used_team_ids, used_volunteer_ids, used_resource_ids, remaining_by_type)
                planned_cases.append(
                    PlannedCaseAssignment(
                        **base_kwargs,
                        assignment_status=BatchPlanStatus.ASSIGNED,
                        selected_recommendation=selected,
                        reasons=["Highest-priority feasible plan selected before lower-priority cases consumed capacity."],
                    )
                )
                continue

            partial = next(
                (
                    recommendation
                    for recommendation in result.recommendations
                    if self._recommendation_available(
                        recommendation,
                        used_team_ids,
                        used_volunteer_ids,
                        remaining_by_type,
                        require_resources=False,
                        case=case,
                    )
                ),
                None,
            )
            if partial is not None:
                partial = self._clip_recommendation_resources(partial, remaining_by_type)
                self._consume_recommendation(partial, used_team_ids, used_volunteer_ids, used_resource_ids, remaining_by_type)
                planned_cases.append(
                    PlannedCaseAssignment(
                        **base_kwargs,
                        assignment_status=BatchPlanStatus.PARTIAL,
                        selected_recommendation=partial,
                        reasons=["Team coverage is available, but not every required resource can be fully allocated."],
                        unmet_requirements=self._unmet_requirements(case, partial, remaining_by_type),
                    )
                )
                continue

            planned_cases.append(
                PlannedCaseAssignment(
                    **base_kwargs,
                    assignment_status=BatchPlanStatus.WAITING,
                    reasons=["Feasible options were consumed by higher-priority cases in this global plan."],
                    unmet_requirements=self._unmet_requirements(case, None, remaining_by_type),
                )
            )

        return {
            "planned_cases": planned_cases,
            "used_team_ids": used_team_ids,
            "used_resource_ids": used_resource_ids,
            "remaining_by_type": remaining_by_type,
        }

    def _batch_reserve_allocator_node(self, state: dict[str, Any]) -> dict[str, Any]:
        payload: BatchPlanningRequest = state["payload"]
        conflicts: list[str] = []
        reserve_team_ids: list[str] = []
        reserve_resource_ids: list[str] = []
        if payload.include_reserve and payload.reserve_policy.mode != ReservePolicyMode.NONE:
            used_team_ids: set[str] = state.get("used_team_ids", set())
            available_teams = [
                team
                for team in state.get("teams", [])
                if team.team_id not in used_team_ids and team.availability_status != AvailabilityStatus.OFFLINE
            ]
            reserve_team_ids.extend(
                self._pick_reserve_teams(available_teams, {"MEDICAL", "FIRST_AID", "AMBULANCE"}, payload.reserve_policy.min_medical_reserve_teams)
            )
            reserve_team_ids.extend(
                self._pick_reserve_teams(
                    [team for team in available_teams if team.team_id not in reserve_team_ids],
                    {"RESCUE", "EVACUATION", "WATER", "BOAT"},
                    payload.reserve_policy.min_rescue_reserve_teams,
                )
            )
            reserve_team_ids = list(dict.fromkeys(reserve_team_ids))
            if len(reserve_team_ids) < payload.reserve_policy.min_medical_reserve_teams + payload.reserve_policy.min_rescue_reserve_teams:
                conflicts.append("Reserve policy could not be fully satisfied after primary allocation.")
            reserve_resource_ids = [
                resource.resource_id
                for resource in state.get("resources", [])
                if resource.resource_id not in state.get("used_resource_ids", set()) and resource.quantity_available > 0
            ][:6]
        return {"reserve_pool_team_ids": reserve_team_ids, "reserve_pool_resource_ids": reserve_resource_ids, "reserve_conflicts": conflicts}

    def _batch_leftover_case_reasoner_node(self, state: dict[str, Any]) -> dict[str, Any]:
        planned_cases: list[PlannedCaseAssignment] = state.get("planned_cases", [])
        for planned in planned_cases:
            if planned.assignment_status == BatchPlanStatus.WAITING and not planned.reasons:
                planned.reasons.append("Valid case deferred because higher-priority assignments consumed scarce assets.")
            if planned.assignment_status == BatchPlanStatus.UNASSIGNED and not planned.reasons:
                planned.reasons.append("No feasible assignment was found with current teams and inventory.")
            if planned.assignment_status == BatchPlanStatus.BLOCKED and not planned.reasons:
                planned.reasons.append("Planner needs operator action before assignment.")
        return {"planned_cases": planned_cases}

    def _batch_preview_node(self, state: dict[str, Any]) -> dict[str, Any]:
        actor: UserContext = state["actor"]
        payload: BatchPlanningRequest = state["payload"]
        plan = BatchDispatchPlan(
            planned_cases=state.get("planned_cases", []),
            reserve_pool_team_ids=state.get("reserve_pool_team_ids", []),
            reserve_pool_resource_ids=state.get("reserve_pool_resource_ids", []),
            conflicts=list(dict.fromkeys([*state.get("reserve_conflicts", [])])),
        )
        self._refresh_batch_plan_summary(plan)
        draft = RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.DISPATCH,
            title="Global dispatch plan for open cases",
            payload={"batch_plan": plan.model_dump(mode="json")},
            confidence=0.86 if plan.planned_cases else 0.35,
            warnings=plan.conflicts,
            display_fields={
                "total_cases": plan.stats.total_cases,
                "assigned": plan.stats.assigned_count,
                "partial": plan.stats.partial_count,
                "waiting": plan.stats.waiting_count,
                "blocked": plan.stats.blocked_count,
                "unassigned": plan.stats.unassigned_count,
            },
        )
        run = GraphRun(
            run_id=f"run-{uuid.uuid4().hex[:10]}",
            org_id=actor.active_org_id or "unassigned",
            graph_name="batch_dispatch_planning_graph",
            status=GraphRunStatus.WAITING_FOR_CONFIRMATION,
            created_by=actor.uid,
            drafts=[draft],
            next_action="confirm_batch_or_edit",
            meta={
                **plan.stats.model_dump(mode="json"),
                "request": payload.model_dump(mode="json"),
            },
        )
        return {"run": run}

    def _planning_priority_score(self, case: CaseRecord, resources: list[ResourceInventory], operator_prompt: str = "") -> float:
        urgency_score = {
            UrgencyKind.CRITICAL: 1.0,
            UrgencyKind.HIGH: 0.8,
            UrgencyKind.MEDIUM: 0.5,
            UrgencyKind.LOW: 0.2,
            UrgencyKind.UNKNOWN: 0.1,
        }.get(case.urgency, 0.1)
        rationale = case.priority_rationale
        extraction = case.extracted_json
        life_risk_score = rationale.life_threat_score if rationale else urgency_score
        population_impact_score = 0.0
        vulnerability_score = rationale.vulnerability_score if rationale else 0.0
        if extraction is not None:
            population_impact_score = min(1.0, (extraction.people_affected or 0) / 100)
            if extraction.vulnerable_groups:
                vulnerability_score = max(vulnerability_score, 0.7)
        travel_feasibility_score = 1.0 if case.geo else (0.35 if case.location_text else 0.0)
        resource_feasibility_score = self._case_resource_feasibility(case, resources)
        operator_override_score = self._operator_override_score(case, operator_prompt)
        return round(
            0.35 * urgency_score
            + 0.20 * life_risk_score
            + 0.15 * population_impact_score
            + 0.10 * travel_feasibility_score
            + 0.10 * resource_feasibility_score
            + 0.05 * vulnerability_score
            + 0.05 * operator_override_score,
            3,
        )

    def _case_resource_feasibility(self, case: CaseRecord, resources: list[ResourceInventory]) -> float:
        extraction = case.extracted_json
        if extraction is None or not extraction.required_resources:
            return 0.8
        available = self._resource_quantities_by_type(resources)
        satisfied = 0
        for need in extraction.required_resources:
            if available.get(need.resource_type, 0) >= (need.quantity or 1):
                satisfied += 1
        return satisfied / max(len(extraction.required_resources), 1)

    def _operator_override_score(self, case: CaseRecord, operator_prompt: str) -> float:
        prompt = operator_prompt.lower().strip()
        if not prompt:
            return 0.0
        candidates = [case.case_id, case.location_text, str(case.urgency)]
        if case.extracted_json is not None:
            candidates.extend([str(case.extracted_json.category), case.extracted_json.subcategory])
        return 1.0 if any(item and str(item).lower() in prompt for item in candidates) else 0.0

    def _resource_quantities_by_type(self, resources: list[ResourceInventory]) -> dict[str, float]:
        quantities: dict[str, float] = {}
        for resource in resources:
            if resource.quantity_available <= 0:
                continue
            quantities[resource.resource_type] = quantities.get(resource.resource_type, 0) + resource.quantity_available
        return quantities

    def _recommendation_available(
        self,
        recommendation: Recommendation,
        used_team_ids: set[str],
        used_volunteer_ids: set[str],
        remaining_by_type: dict[str, float],
        require_resources: bool,
        case: CaseRecord,
    ) -> bool:
        if recommendation.team_id and recommendation.team_id in used_team_ids:
            return False
        if any(volunteer_id in used_volunteer_ids for volunteer_id in recommendation.volunteer_ids):
            return False
        if not require_resources:
            return True
        if self._unmet_requirements(case, recommendation, remaining_by_type):
            return False
        return True

    def _unmet_requirements(
        self,
        case: CaseRecord,
        recommendation: Recommendation | None,
        remaining_by_type: dict[str, float],
    ) -> list[str]:
        extraction = case.extracted_json
        if extraction is None:
            return ["structured extraction"]
        allocations: dict[str, float] = {}
        if recommendation is not None:
            for allocation in recommendation.resource_allocations:
                allocations[allocation.resource_type] = allocations.get(allocation.resource_type, 0) + (allocation.quantity or 1)
        unmet: list[str] = []
        for need in extraction.required_resources:
            required = need.quantity or 1
            allocated = allocations.get(need.resource_type, 0)
            remaining = remaining_by_type.get(need.resource_type, 0)
            if allocated < required or remaining < min(required, allocated or required):
                unmet.append(need.resource_type)
        return list(dict.fromkeys(unmet))

    def _clip_recommendation_resources(self, recommendation: Recommendation, remaining_by_type: dict[str, float]) -> Recommendation:
        clipped = recommendation.model_copy(deep=True)
        allocations = []
        for allocation in clipped.resource_allocations:
            remaining = remaining_by_type.get(allocation.resource_type, 0)
            if remaining <= 0:
                continue
            requested = allocation.quantity or 1
            allocations.append(allocation.model_copy(update={"quantity": min(requested, remaining)}))
        clipped.resource_allocations = allocations
        return clipped

    def _consume_recommendation(
        self,
        recommendation: Recommendation,
        used_team_ids: set[str],
        used_volunteer_ids: set[str],
        used_resource_ids: set[str],
        remaining_by_type: dict[str, float],
    ) -> None:
        if recommendation.team_id:
            used_team_ids.add(recommendation.team_id)
        used_volunteer_ids.update(recommendation.volunteer_ids)
        used_resource_ids.update(recommendation.resource_ids)
        for allocation in recommendation.resource_allocations:
            decrement = allocation.quantity or 1
            remaining_by_type[allocation.resource_type] = max(remaining_by_type.get(allocation.resource_type, 0) - decrement, 0)

    def _pick_reserve_teams(self, teams: list[Team], capability_keywords: set[str], count: int) -> list[str]:
        if count <= 0:
            return []
        matching = [
            team
            for team in teams
            if {tag.upper() for tag in team.capability_tags} & capability_keywords
        ]
        matching.sort(key=lambda item: (-item.reliability_score, item.active_dispatches, item.team_id))
        return [team.team_id for team in matching[:count]]

    def _refresh_batch_plan_summary(self, plan: BatchDispatchPlan) -> None:
        stats = BatchPlanningStats(
            total_cases=len(plan.planned_cases),
            assigned_count=sum(1 for item in plan.planned_cases if item.assignment_status == BatchPlanStatus.ASSIGNED),
            partial_count=sum(1 for item in plan.planned_cases if item.assignment_status == BatchPlanStatus.PARTIAL),
            waiting_count=sum(1 for item in plan.planned_cases if item.assignment_status == BatchPlanStatus.WAITING),
            blocked_count=sum(1 for item in plan.planned_cases if item.assignment_status == BatchPlanStatus.BLOCKED),
            unassigned_count=sum(1 for item in plan.planned_cases if item.assignment_status == BatchPlanStatus.UNASSIGNED),
            reserve_team_count=len(plan.reserve_pool_team_ids),
            reserve_resource_count=len(plan.reserve_pool_resource_ids),
            conflict_count=len(plan.conflicts) + sum(len(item.conflict_flags) for item in plan.planned_cases),
        )
        plan.stats = stats
        plan.planning_summary = (
            f"{stats.total_cases} cases evaluated: {stats.assigned_count} assigned, "
            f"{stats.partial_count} partial, {stats.waiting_count} waiting, "
            f"{stats.blocked_count} blocked, {stats.unassigned_count} unassigned. "
            f"{stats.reserve_team_count} reserve teams retained."
        )

    def _batch_plan_from_run(self, run: GraphRun) -> tuple[RecordDraft, BatchDispatchPlan]:
        draft = next(
            (
                item
                for item in run.drafts
                if item.draft_type == DraftRecordType.DISPATCH and isinstance(item.payload.get("batch_plan"), dict)
            ),
            None,
        )
        if draft is None:
            raise KeyError("batch_plan")
        return draft, BatchDispatchPlan.model_validate(draft.payload["batch_plan"])

    def _assignment_from_planned_case(
        self,
        planned: PlannedCaseAssignment,
        plan: BatchDispatchPlan,
        run: GraphRun,
        actor: UserContext,
    ) -> AssignmentDecision | None:
        recommendation = planned.selected_recommendation
        if recommendation is None:
            return None
        reserve_team_ids = [
            item.team_id
            for item in planned.reserve_recommendations
            if item.team_id
        ] or plan.reserve_pool_team_ids
        return AssignmentDecision(
            assignment_id=f"asg-{uuid.uuid4().hex[:10]}",
            org_id=run.org_id,
            case_id=planned.case_id,
            incident_id=planned.case_id,
            team_id=recommendation.team_id,
            volunteer_ids=recommendation.volunteer_ids,
            resource_ids=recommendation.resource_ids,
            resource_allocations=recommendation.resource_allocations,
            reserve_team_ids=list(dict.fromkeys(reserve_team_ids)),
            match_score=recommendation.match_score,
            eta_minutes=recommendation.eta_minutes,
            route_summary=recommendation.route_summary,
            confirmed_by=actor.uid,
        )

    def _save_graph_run(self, run: GraphRun) -> GraphRun:
        self._compact_graph_run_for_firestore(run)
        return self.repository.save_graph_run(run)

    def _compact_graph_run_for_firestore(self, run: GraphRun) -> None:
        """Firestore documents are capped at 1 MiB, so previews keep provenance concise."""
        original_bytes = len(json.dumps(run.model_dump(mode="json"), default=str).encode("utf-8"))
        for artifact in run.source_artifacts:
            artifact.text = self._truncate_text(artifact.text, MAX_ARTIFACT_TEXT_CHARS)
            artifact.docling_markdown = self._truncate_text(artifact.docling_markdown or "", MAX_ARTIFACT_TEXT_CHARS)
            artifact.docling_json = self._compact_json_value(artifact.docling_json, depth=3)
            artifact.parse_warnings = self._compact_string_list(artifact.parse_warnings, 20, MAX_WARNING_CHARS)
            artifact.detected_languages = self._compact_string_list(artifact.detected_languages, 8, 40)

        for draft in run.drafts:
            draft.title = self._truncate_text(draft.title, 220)
            draft.warnings = self._compact_string_list(draft.warnings, MAX_WARNINGS_PER_DRAFT, MAX_WARNING_CHARS)
            draft.source_fragment = self._truncate_text(draft.source_fragment or "", MAX_SOURCE_FRAGMENT_CHARS) or None
            draft.source_headers = self._compact_string_list(draft.source_headers, 24, 40)
            draft.normalization_trace = self._compact_string_list(draft.normalization_trace, 2, 80)
            draft.display_fields = self._compact_json_value(draft.display_fields, depth=3)
            draft.payload = self._compact_draft_payload(draft.payload)

        compacted_bytes = len(json.dumps(run.model_dump(mode="json"), default=str).encode("utf-8"))
        run.meta = {
            **run.meta,
            "storage_compacted": compacted_bytes < original_bytes,
            "estimated_graph_run_bytes": compacted_bytes,
            "estimated_graph_run_bytes_before_compaction": original_bytes,
        }

    def _compact_draft_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        compacted = dict(payload)
        for key in ("source_raw_input", "working_input", "raw_input"):
            if isinstance(compacted.get(key), str):
                compacted[key] = self._truncate_text(compacted[key], MAX_DRAFT_TEXT_CHARS)
        if compacted.get("working_input") == compacted.get("source_raw_input"):
            compacted.pop("working_input", None)
        if compacted.get("raw_input") == compacted.get("source_raw_input"):
            compacted.pop("raw_input", None)
        if isinstance(compacted.get("source_fragment"), str):
            compacted["source_fragment"] = self._truncate_text(compacted["source_fragment"], MAX_SOURCE_FRAGMENT_CHARS)
        if isinstance(compacted.get("source_row"), dict):
            compacted["source_row"] = self._compact_row_dict(compacted["source_row"])
        compacted.pop("original_source_row", None)
        if isinstance(compacted.get("source_headers"), list):
            compacted["source_headers"] = self._compact_string_list(compacted["source_headers"], 24, 40)
        if isinstance(compacted.get("normalization_trace"), list):
            compacted["normalization_trace"] = self._compact_string_list(compacted["normalization_trace"], 2, 80)
        if isinstance(compacted.get("parse_warnings"), list):
            compacted["parse_warnings"] = self._compact_string_list(compacted["parse_warnings"], 6, MAX_WARNING_CHARS)
        if isinstance(compacted.get("provider_fallbacks"), list):
            compacted["provider_fallbacks"] = self._compact_string_list(compacted["provider_fallbacks"], 5, 100)
        if isinstance(compacted.get("operator_prompt_history"), list):
            compacted["operator_prompt_history"] = self._compact_string_list(compacted["operator_prompt_history"], 5, 240)
        if isinstance(compacted.get("duplicate_candidates"), list):
            compacted["duplicate_candidates"] = compacted["duplicate_candidates"][:MAX_DUPLICATE_CANDIDATES]
        compacted.pop("source_fragment", None)
        compacted.pop("source_headers", None)
        compacted.pop("normalization_trace", None)
        return compacted

    def _compact_row_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        priority = [
            "id",
            "source_id",
            "title",
            "summary",
            "event_type",
            "category",
            "location_text",
            "lat",
            "lng",
            "geo_lat",
            "geo_long",
            "severity_value",
            "severity_unit",
            "people_affected",
            "required_resources",
            "source_confidence",
            "source",
            "link",
            "team_id",
            "display_name",
            "capability_tags",
            "base_label",
            "resource_id",
            "resource_type",
            "quantity_available",
            "location_label",
        ]
        compacted: dict[str, Any] = {}
        ordered_keys = [key for key in priority if key in row]
        ordered_keys.extend(key for key in row if key not in ordered_keys)
        for index, key in enumerate(ordered_keys):
            if index >= 12:
                compacted["_truncated_keys"] = len(row) - index
                break
            value = row[key]
            compacted[str(key)[:80]] = self._truncate_text(str(value), MAX_ROW_VALUE_CHARS)
        return compacted

    def _compact_json_value(self, value: Any, *, depth: int) -> Any:
        if depth <= 0:
            return self._truncate_text(str(value), MAX_ARTIFACT_JSON_STRING_CHARS)
        if isinstance(value, dict):
            compacted: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 40:
                    compacted["_truncated_keys"] = len(value) - index
                    break
                compacted[str(key)[:80]] = self._compact_json_value(item, depth=depth - 1)
            return compacted
        if isinstance(value, list):
            items = [self._compact_json_value(item, depth=depth - 1) for item in value[:30]]
            if len(value) > 30:
                items.append({"_truncated_items": len(value) - 30})
            return items
        if isinstance(value, str):
            return self._truncate_text(value, MAX_ARTIFACT_JSON_STRING_CHARS)
        return value

    def _compact_string_list(self, values: list[Any], max_items: int, max_chars: int) -> list[str]:
        selected = values[:max_items]
        if len(values) > max_items and max_items > 1:
            selected = [*values[: max_items - 1], values[-1]]
        compacted = [self._truncate_text(str(value), max_chars) for value in selected if str(value or "").strip()]
        if len(values) > max_items:
            compacted.append(f"... {len(values) - max_items} more item(s) truncated")
        return compacted

    def _truncate_text(self, value: str, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value
        return f"{value[:max_chars].rstrip()} ...[truncated {len(value) - max_chars} chars]"

    def _now(self):
        from app.models.domain import utcnow

        return utcnow()

    def _dispatch_reasoning_summary(
        self,
        recommendations: list[Any],
        reserves: list[Any],
        conflicts: list[str],
        reason: str | None,
    ) -> str:
        if not recommendations:
            return reason or "No feasible dispatch option found."
        top = recommendations[0]
        team_id = getattr(top, "team_id", None)
        eta = getattr(top, "eta_minutes", None)
        score = getattr(top, "match_score", 0)
        reserve_text = f" {len(reserves)} reserve option(s) retained." if reserves else ""
        conflict_text = f" {len(conflicts)} warning(s) require operator awareness." if conflicts else ""
        return f"Selected {team_id or 'top available team'} with match score {score:.2f} and ETA {eta if eta is not None else 'unknown'} minutes.{reserve_text}{conflict_text}"

    def _drafts_from_document_batch(
        self,
        batch: Any,
        operator_prompt: str | None,
        source_text: str,
        target: str,
        result: Any,
    ) -> list[RecordDraft]:
        normalized_target = (target or "incidents").lower()
        allow_incidents = normalized_target in {"incidents", "incident", "mixed", "all"}
        allow_teams = normalized_target in {"teams", "team", "mixed", "all"}
        allow_resources = normalized_target in {"resources", "resource", "mixed", "all"}
        drafts: list[RecordDraft] = []

        if allow_incidents:
            for index, extraction in enumerate(batch.incidents, start=1):
                raw_input = f"{batch.document_summary or 'Document incident draft'}\n{source_text[:12000]}"
                warnings = [
                    *getattr(result, "warnings", []),
                    *extraction.data_quality.needs_followup_questions,
                ]
                drafts.append(
                    RecordDraft(
                        draft_id=f"draft-{uuid.uuid4().hex[:10]}",
                        draft_type=DraftRecordType.INCIDENT,
                        title=f"{extraction.category} - {extraction.location_text or 'Location pending'}",
                        payload={
                            "source_raw_input": source_text,
                            "working_input": raw_input,
                            "raw_input": raw_input,
                            "extracted": extraction.model_dump(mode="json"),
                            "geo": None,
                            "location_confidence": "UNKNOWN" if extraction.data_quality.missing_location else "APPROXIMATE",
                            "operator_prompt": operator_prompt,
                            "operator_prompt_history": [operator_prompt] if operator_prompt else [],
                            "revision_count": 0,
                            "provider_used": getattr(result, "provider_used", "Unknown"),
                            "provider_fallbacks": getattr(result, "provider_fallbacks", []),
                            "schema_validated": getattr(result, "schema_validated", True),
                            "duplicate_candidates": [],
                            "geo_resolution_status": "pending",
                            "source_fragment": source_text[:12000],
                            "source_headers": [],
                            "normalization_trace": [],
                            "extraction_mode": "model_batch" if getattr(result, "provider_used", "Unknown") != "Heuristic" else "heuristic",
                            "adapter_confidence": None,
                        },
                        confidence=extraction.confidence,
                        warnings=list(dict.fromkeys(warnings)),
                        source_row_index=index,
                        display_fields=self._incident_display_fields(extraction, None),
                        map_status=LocationConfidence.UNKNOWN if extraction.data_quality.missing_location else LocationConfidence.APPROXIMATE,
                        source_fragment=source_text[:12000],
                        extraction_mode="model_batch" if getattr(result, "provider_used", "Unknown") != "Heuristic" else "heuristic",
                        geo_resolution_status="pending",
                    )
                )

        if allow_teams:
            for index, payload in enumerate(batch.teams, start=1):
                team = Team(
                    team_id=payload.team_id or f"TEAM-{uuid.uuid4().hex[:8].upper()}",
                    display_name=payload.display_name or f"Team draft {index}",
                    capability_tags=[tag.upper().replace(" ", "_") for tag in payload.capability_tags] or ["GENERAL_RESPONSE"],
                    member_ids=payload.member_ids,
                    service_radius_km=payload.service_radius_km if payload.service_radius_km is not None else 30,
                    base_label=payload.base_label or "Location pending",
                    base_geo=payload.base_geo,
                    current_label=payload.current_label or payload.base_label,
                    current_geo=payload.current_geo or payload.base_geo,
                    availability_status=payload.availability_status or AvailabilityStatus.AVAILABLE,
                    active_dispatches=payload.active_dispatches or 0,
                    reliability_score=payload.reliability_score if payload.reliability_score is not None else 0.75,
                    evidence_ids=payload.evidence_ids,
                    notes=[*payload.notes, *([operator_prompt] if operator_prompt else [])],
                )
                drafts.append(self._team_draft_from_team(team, source_text, operator_prompt, index, getattr(result, "provider_used", "Unknown")))

        if allow_resources:
            for index, payload in enumerate(batch.resources, start=1):
                resource = ResourceInventory(
                    resource_id=payload.resource_id or f"RES-{uuid.uuid4().hex[:8].upper()}",
                    owning_team_id=payload.owning_team_id,
                    resource_type=payload.resource_type.upper().replace(" ", "_"),
                    quantity_available=payload.quantity_available or 0,
                    location_label=payload.location_label or "Location pending",
                    location=payload.location,
                    current_label=payload.current_label or payload.location_label,
                    current_geo=payload.current_geo or payload.location,
                    constraints=[item.upper().replace(" ", "_") for item in payload.constraints],
                    evidence_ids=payload.evidence_ids,
                    image_url=payload.image_url,
                )
                drafts.append(self._resource_draft_from_resource(resource, source_text, operator_prompt, index, getattr(result, "provider_used", "Unknown")))

        return drafts

    def _draft_from_payload(
        self,
        payload: GraphRunRequest,
        markdown: str,
        parse_warnings: list[str] | None = None,
    ) -> RecordDraft:
        if payload.target in {"teams", "resources", "mixed", "all"}:
            result = self.extractor.extract_document_batch_with_metadata(markdown, "manual_payload")
            drafts = self._drafts_from_document_batch(result.batch, payload.operator_prompt, markdown, payload.target, result)
            if drafts:
                drafts[0].warnings = list(dict.fromkeys([*drafts[0].warnings, *(parse_warnings or [])]))
                return drafts[0]
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
            original = {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
            cleaned = self._canonicalize_csv_row(original)
            row_fragment = self._csv_row_fragment(original)
            source_headers = normalized_headers
            normalization_trace = self._normalization_trace(original, cleaned)
            row_key = "|".join(original.get(header, "") for header in normalized_headers)
            if not row_key.strip():
                continue
            if row_key in seen_rows:
                warnings.append(f"Skipped duplicate row {row_index}.")
                continue
            has_operational_signal = self._row_has_operational_signal(cleaned, target)
            if not has_operational_signal:
                warnings.append(f"Skipped row {row_index}: no {target} fields found.")
                continue
            seen_rows.add(row_key)
            try:
                row_drafts = self._drafts_from_csv_row_batch(
                    original=original,
                    cleaned=cleaned,
                    row_fragment=row_fragment,
                    source_headers=source_headers,
                    normalization_trace=normalization_trace,
                    target=target,
                    operator_prompt=operator_prompt,
                    row_index=row_index,
                )
                if row_drafts:
                    drafts.extend(row_drafts)
                else:
                    warnings.append(f"Skipped row {row_index}: no operational records extracted.")
            except Exception as exc:
                warnings.append(f"Row {row_index} could not be drafted: {type(exc).__name__}: {exc}")
        if not drafts:
            warnings.append("No usable rows were found in the CSV.")
        return drafts, warnings

    def _drafts_from_csv_row_batch(
        self,
        *,
        original: dict[str, str],
        cleaned: dict[str, str],
        row_fragment: str,
        source_headers: list[str],
        normalization_trace: list[str],
        target: str,
        operator_prompt: str | None,
        row_index: int,
    ) -> list[RecordDraft]:
        result = self.extractor.extract_row_batch_with_metadata(
            row_fragment,
            "csv_row",
            target_hint=target,
            row_context={
                "source_headers": source_headers,
                "source_row_index": row_index,
                "original_row": original,
                "normalized_row": cleaned,
            },
        )
        row_drafts = self._drafts_from_document_batch(result.batch, operator_prompt, row_fragment, "mixed", result)
        row_drafts = [draft for draft in row_drafts if self._draft_matches_target(draft, target)]
        for draft in row_drafts:
            self._apply_csv_context_to_row_draft(draft, cleaned, original)
            draft.source_row_index = row_index
            draft.payload["source_row"] = cleaned
            draft.payload["original_source_row"] = original
            draft.payload["source_fragment"] = row_fragment
            draft.payload["source_headers"] = source_headers
            draft.payload["normalization_trace"] = normalization_trace
            draft.payload["extraction_mode"] = "model_row" if result.provider_used != "Heuristic" else "heuristic"
            draft.payload["adapter_confidence"] = None
            self._apply_draft_provenance(
                draft,
                source_fragment=row_fragment,
                source_headers=source_headers,
                normalization_trace=[*normalization_trace, *result.warnings],
                extraction_mode=str(draft.payload["extraction_mode"]),
                adapter_confidence=None,
            )
        return row_drafts

    def _draft_matches_target(self, draft: RecordDraft, target: str) -> bool:
        normalized_target = (target or "incidents").lower()
        if normalized_target in {"mixed", "all"}:
            return True
        expected = {
            "incidents": DraftRecordType.INCIDENT,
            "incident": DraftRecordType.INCIDENT,
            "cases": DraftRecordType.INCIDENT,
            "case": DraftRecordType.INCIDENT,
            "teams": DraftRecordType.TEAM,
            "team": DraftRecordType.TEAM,
            "resources": DraftRecordType.RESOURCE,
            "resource": DraftRecordType.RESOURCE,
        }.get(normalized_target, DraftRecordType.INCIDENT)
        return draft.draft_type == expected

    def _apply_csv_context_to_row_draft(self, draft: RecordDraft, cleaned: dict[str, str], original: dict[str, str]) -> None:
        """Apply source-row facts that should stay exact without choosing an adapter.

        The extractor still decides whether the row is an incident, team, or resource.
        This pass only preserves literal row facts such as coordinates or a provided
        location label so map previews do not lose precision.
        """
        geo = self._geo_from_row(cleaned)
        try:
            if draft.draft_type == DraftRecordType.INCIDENT:
                extraction = IncidentExtraction.model_validate(draft.payload.get("extracted"))
                if cleaned.get("location_text") and not extraction.location_text:
                    extraction.location_text = cleaned["location_text"]
                    extraction.data_quality.missing_location = False
                people_affected = self._parse_people_affected(
                    cleaned.get("people_affected") or cleaned.get("summary") or cleaned.get("raw_input")
                )
                if people_affected is not None and extraction.people_affected is None:
                    extraction.people_affected = people_affected
                    extraction.data_quality.missing_quantity = False
                if self._original_row_has_any(original, {"required_resources", "resources", "needs", "required supplies"}):
                    resource_needs = self._resource_needs_from_value(cleaned.get("required_resources"))
                    if resource_needs and not extraction.required_resources:
                        extraction.required_resources = resource_needs
                        extraction.data_quality.missing_quantity = any(item.quantity is None for item in resource_needs)
                draft.payload["extracted"] = extraction.model_dump(mode="json")
                if geo is not None:
                    draft.payload["geo"] = geo.model_dump(mode="json")
                    draft.payload["location_confidence"] = LocationConfidence.EXACT.value
                    draft.payload["geo_resolution_status"] = "direct_coordinates"
                    draft.geo_resolution_status = "direct_coordinates"
                elif cleaned.get("location_text") and draft.payload.get("location_confidence") == LocationConfidence.UNKNOWN.value:
                    draft.payload["location_confidence"] = LocationConfidence.APPROXIMATE.value
            elif draft.draft_type == DraftRecordType.TEAM:
                team = Team.model_validate(draft.payload.get("team"))
                if cleaned.get("team_id"):
                    team.team_id = cleaned["team_id"]
                if cleaned.get("display_name"):
                    team.display_name = cleaned["display_name"]
                capabilities = self._split_tags(cleaned.get("capability_tags"))
                if capabilities:
                    team.capability_tags = capabilities
                if cleaned.get("availability_status"):
                    team.availability_status = self._availability(cleaned.get("availability_status"))
                service_radius = self._parse_float(cleaned.get("service_radius_km"), team.service_radius_km)
                team.service_radius_km = service_radius
                if cleaned.get("base_label") and not team.base_label:
                    team.base_label = cleaned["base_label"]
                if cleaned.get("current_label") and not team.current_label:
                    team.current_label = cleaned["current_label"]
                if geo is not None and team.base_geo is None and team.current_geo is None:
                    team.base_geo = geo
                    team.current_geo = geo
                    draft.payload["geo_resolution_status"] = "direct_coordinates"
                    draft.geo_resolution_status = "direct_coordinates"
                draft.payload["team"] = team.model_dump(mode="json")
            elif draft.draft_type == DraftRecordType.RESOURCE:
                resource = ResourceInventory.model_validate(draft.payload.get("resource"))
                if cleaned.get("resource_id"):
                    resource.resource_id = cleaned["resource_id"]
                if cleaned.get("resource_type"):
                    resource.resource_type = cleaned["resource_type"].strip().upper().replace(" ", "_")
                quantity = self._parse_float(cleaned.get("quantity_available") or cleaned.get("quantity"), resource.quantity_available)
                resource.quantity_available = max(quantity, 0.0)
                if cleaned.get("owning_team_id"):
                    resource.owning_team_id = cleaned["owning_team_id"]
                if cleaned.get("location_label"):
                    resource.location_label = cleaned["location_label"]
                if cleaned.get("current_label"):
                    resource.current_label = cleaned["current_label"]
                if geo is not None and resource.location is None and resource.current_geo is None:
                    resource.location = geo
                    resource.current_geo = geo
                    draft.payload["geo_resolution_status"] = "direct_coordinates"
                    draft.geo_resolution_status = "direct_coordinates"
                draft.payload["resource"] = resource.model_dump(mode="json")
            self._refresh_draft_display(draft)
        except Exception as exc:
            draft.warnings = [*draft.warnings, f"CSV row context could not be applied: {type(exc).__name__}."]

    def _original_row_has_any(self, row: dict[str, str], names: set[str]) -> bool:
        normalized_names = {self._normalize_csv_key(name) for name in names}
        return any(self._normalize_csv_key(key) in normalized_names and bool(value) for key, value in row.items())

    def _apply_draft_provenance(
        self,
        draft: RecordDraft,
        *,
        source_fragment: str | None,
        source_headers: list[str],
        normalization_trace: list[str],
        extraction_mode: str | None,
        adapter_confidence: float | None,
    ) -> RecordDraft:
        draft.source_fragment = source_fragment
        draft.source_headers = source_headers
        draft.normalization_trace = list(dict.fromkeys(item for item in normalization_trace if item))
        draft.extraction_mode = extraction_mode
        draft.adapter_confidence = adapter_confidence
        draft.geo_resolution_status = str(draft.payload.get("geo_resolution_status") or "") or None
        draft.payload["source_fragment"] = source_fragment
        draft.payload["source_headers"] = source_headers
        draft.payload["normalization_trace"] = draft.normalization_trace
        draft.payload["extraction_mode"] = extraction_mode
        draft.payload["adapter_confidence"] = adapter_confidence
        return draft

    def _csv_row_fragment(self, row: dict[str, str]) -> str:
        return " | ".join(f"{key}: {value}" for key, value in row.items() if str(value or "").strip())

    def _normalization_trace(self, original: dict[str, str], cleaned: dict[str, str]) -> list[str]:
        trace: list[str] = []
        original_keys = set(original)
        for key, value in cleaned.items():
            if key in original_keys or not str(value or "").strip():
                continue
            trace.append(f"Mapped/inferred {key}='{str(value)[:80]}'")
        return trace[:24]

    def _row_has_operational_signal(self, row: dict[str, str], target: str) -> bool:
        if self._row_matches_target(row, target):
            return True
        text = " ".join(str(value or "") for value in row.values()).lower()
        terms = {
            "incident",
            "emergency",
            "disaster",
            "earthquake",
            "flood",
            "fire",
            "rescue",
            "medical",
            "shelter",
            "evacuation",
            "team",
            "volunteer",
            "responder",
            "crew",
            "unit",
            "skill",
            "capability",
            "certified",
            "available",
            "stock",
            "inventory",
            "quantity",
            "warehouse",
            "depot",
            "resource",
            "ambulance",
            "boat",
            "water",
            "food",
            "medicine",
            "kit",
        }
        return any(term in text for term in terms)

    def _team_draft_from_row(
        self,
        row: dict[str, str],
        operator_prompt: str | None,
        row_index: int | None = None,
        *,
        provider_used: str = "CSV Fallback Parser",
        extraction_mode: str = "csv_fallback_parser",
        adapter_confidence: float | None = None,
    ) -> RecordDraft:
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
            active_dispatches=self._parse_int(row.get("active_dispatches"), 0),
            reliability_score=self._parse_float(row.get("reliability_score"), 0.8),
            evidence_ids=self._split_tags(row.get("evidence_ids")),
            notes=[operator_prompt] if operator_prompt else [],
        )
        source_fragment = " | ".join(value for value in row.values() if value)
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.TEAM,
            title=f"{team.display_name} ({', '.join(team.capability_tags[:2])})",
            payload={
                "source_raw_input": source_fragment,
                "working_input": source_fragment,
                "raw_input": source_fragment,
                "source_row": row,
                "team": team.model_dump(mode="json"),
                "operator_prompt": operator_prompt,
                "operator_prompt_history": [operator_prompt] if operator_prompt else [],
                "revision_count": 0,
                "provider_used": provider_used,
                "provider_fallbacks": [],
                "parse_warnings": [],
                "schema_validated": True,
                "duplicate_candidates": [],
                "geo_resolution_status": "direct_coordinates" if (team.current_geo or team.base_geo) else "pending",
                "extraction_mode": extraction_mode,
                "adapter_confidence": adapter_confidence,
            },
            confidence=0.78,
            warnings=[] if team.base_label != "Location pending" else ["Team base location is missing."],
            source_row_index=row_index,
            display_fields=self._team_display_fields(team),
            map_status=LocationConfidence.EXACT if (team.current_geo or team.base_geo) else LocationConfidence.UNKNOWN,
            source_fragment=source_fragment,
            extraction_mode=extraction_mode,
            adapter_confidence=adapter_confidence,
            geo_resolution_status="direct_coordinates" if (team.current_geo or team.base_geo) else "pending",
        )

    def _team_draft_from_team(
        self,
        team: Team,
        source_text: str,
        operator_prompt: str | None,
        row_index: int | None,
        provider_used: str,
    ) -> RecordDraft:
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.TEAM,
            title=f"{team.display_name} ({', '.join(team.capability_tags[:2])})",
            payload={
                "source_raw_input": source_text,
                "working_input": source_text,
                "raw_input": source_text,
                "team": team.model_dump(mode="json"),
                "operator_prompt": operator_prompt,
                "operator_prompt_history": [operator_prompt] if operator_prompt else [],
                "revision_count": 0,
                "provider_used": provider_used,
                "provider_fallbacks": [],
                "parse_warnings": [],
                "schema_validated": True,
                "duplicate_candidates": [],
                "geo_resolution_status": "pending",
                "extraction_mode": "csv_fallback_parser" if provider_used == "CSV Fallback Parser" else "model_batch",
                "adapter_confidence": None,
            },
            confidence=0.74,
            warnings=[] if team.base_label != "Location pending" else ["Team base location is missing."],
            source_row_index=row_index,
            display_fields=self._team_display_fields(team),
            map_status=LocationConfidence.EXACT if (team.current_geo or team.base_geo) else LocationConfidence.UNKNOWN,
            source_fragment=source_text,
            extraction_mode="csv_fallback_parser" if provider_used == "CSV Fallback Parser" else "model_batch",
            geo_resolution_status="pending",
        )

    def _resource_draft_from_row(
        self,
        row: dict[str, str],
        operator_prompt: str | None,
        row_index: int | None = None,
        *,
        provider_used: str = "CSV Fallback Parser",
        extraction_mode: str = "csv_fallback_parser",
        adapter_confidence: float | None = None,
    ) -> RecordDraft:
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
            evidence_ids=self._split_tags(row.get("evidence_ids")),
            image_url=row.get("image_url") or None,
        )
        source_fragment = " | ".join(value for value in row.values() if value)
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.RESOURCE,
            title=f"{resource.resource_type} ({resource.quantity_available:g} available)",
            payload={
                "source_raw_input": source_fragment,
                "working_input": source_fragment,
                "raw_input": source_fragment,
                "source_row": row,
                "resource": resource.model_dump(mode="json"),
                "operator_prompt": operator_prompt,
                "operator_prompt_history": [operator_prompt] if operator_prompt else [],
                "revision_count": 0,
                "provider_used": provider_used,
                "provider_fallbacks": [],
                "parse_warnings": [],
                "schema_validated": True,
                "duplicate_candidates": [],
                "geo_resolution_status": "direct_coordinates" if (resource.current_geo or resource.location) else "pending",
                "extraction_mode": extraction_mode,
                "adapter_confidence": adapter_confidence,
            },
            confidence=0.78 if resource.quantity_available > 0 else 0.45,
            warnings=[] if resource.location_label != "Location pending" else ["Resource location is missing."],
            source_row_index=row_index,
            display_fields=self._resource_display_fields(resource),
            map_status=LocationConfidence.EXACT if (resource.current_geo or resource.location) else LocationConfidence.UNKNOWN,
            source_fragment=source_fragment,
            extraction_mode=extraction_mode,
            adapter_confidence=adapter_confidence,
            geo_resolution_status="direct_coordinates" if (resource.current_geo or resource.location) else "pending",
        )

    def _resource_draft_from_resource(
        self,
        resource: ResourceInventory,
        source_text: str,
        operator_prompt: str | None,
        row_index: int | None,
        provider_used: str,
    ) -> RecordDraft:
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.RESOURCE,
            title=f"{resource.resource_type} ({resource.quantity_available:g} available)",
            payload={
                "source_raw_input": source_text,
                "working_input": source_text,
                "raw_input": source_text,
                "resource": resource.model_dump(mode="json"),
                "operator_prompt": operator_prompt,
                "operator_prompt_history": [operator_prompt] if operator_prompt else [],
                "revision_count": 0,
                "provider_used": provider_used,
                "provider_fallbacks": [],
                "parse_warnings": [],
                "schema_validated": True,
                "duplicate_candidates": [],
                "geo_resolution_status": "pending",
                "extraction_mode": "csv_fallback_parser" if provider_used == "CSV Fallback Parser" else "model_batch",
                "adapter_confidence": None,
            },
            confidence=0.72 if resource.quantity_available > 0 else 0.45,
            warnings=[] if resource.location_label != "Location pending" else ["Resource location is missing."],
            source_row_index=row_index,
            display_fields=self._resource_display_fields(resource),
            map_status=LocationConfidence.EXACT if (resource.current_geo or resource.location) else LocationConfidence.UNKNOWN,
            source_fragment=source_text,
            extraction_mode="csv_fallback_parser" if provider_used == "CSV Fallback Parser" else "model_batch",
            geo_resolution_status="pending",
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

    def _enrich_drafts_with_geocodes(self, drafts: list[RecordDraft]) -> list[RecordDraft]:
        for draft in drafts:
            try:
                if draft.draft_type == DraftRecordType.INCIDENT:
                    extraction = IncidentExtraction.model_validate(draft.payload.get("extracted"))
                    geo_payload = draft.payload.get("geo")
                    if isinstance(geo_payload, dict):
                        draft.payload["geo_resolution_status"] = "direct_coordinates"
                        self._refresh_draft_display(draft)
                        continue
                    if extraction.location_text and not extraction.data_quality.missing_location:
                        geo = self.geocoder.geocode_sync(extraction.location_text)
                        if geo is not None:
                            draft.payload["geo"] = geo.model_dump(mode="json")
                            draft.payload["location_confidence"] = "APPROXIMATE"
                            draft.payload["geo_resolution_status"] = "geocoded"
                        else:
                            draft.payload["geo_resolution_status"] = "not_found"
                            draft.warnings = [*draft.warnings, "Location text could not be geocoded; operator should confirm a map pin."]
                    self._refresh_draft_display(draft)
                elif draft.draft_type == DraftRecordType.TEAM:
                    team = Team.model_validate(draft.payload.get("team"))
                    if not (team.current_geo or team.base_geo) and team.base_label and team.base_label != "Location pending":
                        geo = self.geocoder.geocode_sync(team.base_label)
                        if geo is not None:
                            team.base_geo = geo
                            team.current_geo = team.current_geo or geo
                            draft.payload["team"] = team.model_dump(mode="json")
                            draft.payload["geo_resolution_status"] = "geocoded"
                        else:
                            draft.payload["geo_resolution_status"] = "not_found"
                    self._refresh_draft_display(draft)
                elif draft.draft_type == DraftRecordType.RESOURCE:
                    resource = ResourceInventory.model_validate(draft.payload.get("resource"))
                    if not (resource.current_geo or resource.location) and resource.location_label and resource.location_label != "Location pending":
                        geo = self.geocoder.geocode_sync(resource.location_label)
                        if geo is not None:
                            resource.location = geo
                            resource.current_geo = resource.current_geo or geo
                            draft.payload["resource"] = resource.model_dump(mode="json")
                            draft.payload["geo_resolution_status"] = "geocoded"
                        else:
                            draft.payload["geo_resolution_status"] = "not_found"
                    self._refresh_draft_display(draft)
            except Exception as exc:
                draft.payload["geo_resolution_status"] = "failed"
                draft.warnings = [*draft.warnings, f"Geocode enrichment failed: {type(exc).__name__}."]
        return drafts

    def _enrich_drafts_with_duplicates(self, drafts: list[RecordDraft], org_id: str) -> list[RecordDraft]:
        open_cases = [case for case in self.repository.list_cases() if case.org_id == org_id]
        for draft in drafts:
            if draft.draft_type != DraftRecordType.INCIDENT:
                continue
            try:
                extraction = IncidentExtraction.model_validate(draft.payload.get("extracted"))
                geo_payload = draft.payload.get("geo")
                temp = CaseRecord(
                    case_id=draft.draft_id,
                    org_id=org_id,
                    raw_input=str(draft.payload.get("source_raw_input") or draft.payload.get("raw_input") or draft.title),
                    source_channel="GRAPH1_PREVIEW",
                    extracted_json=extraction,
                    location_text=extraction.location_text,
                    geo=GeoPoint.model_validate(geo_payload) if isinstance(geo_payload, dict) else None,
                    location_confidence=LocationConfidence(draft.payload.get("location_confidence", "UNKNOWN")),
                )
                candidates = self.duplicate_service.find_duplicate_candidates(temp, open_cases)
                draft.payload["duplicate_candidates"] = [item.model_dump(mode="json") for item in candidates]
                if candidates:
                    draft.warnings = [*draft.warnings, f"Possible duplicate of {candidates[0].record_id}: {candidates[0].reason}"]
            except Exception:
                continue
        return drafts

    def _run_meta(self, drafts: list[RecordDraft], warnings: list[str] | None = None) -> dict[str, Any]:
        active = [draft for draft in drafts if not draft.removed]
        return {
            "draft_counts": {
                "INCIDENT": sum(1 for draft in active if draft.draft_type == DraftRecordType.INCIDENT),
                "TEAM": sum(1 for draft in active if draft.draft_type == DraftRecordType.TEAM),
                "RESOURCE": sum(1 for draft in active if draft.draft_type == DraftRecordType.RESOURCE),
                "DISPATCH": sum(1 for draft in active if draft.draft_type == DraftRecordType.DISPATCH),
            },
            "warning_count": sum(1 for draft in active if draft.warnings) + len(warnings or []),
            "duplicate_count": sum(1 for draft in active if draft.payload.get("duplicate_candidates")),
            "removed_count": sum(1 for draft in drafts if draft.removed),
            "committed_count": 0,
        }

    def _run_async(self, awaitable: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(awaitable)
            finally:
                new_loop.close()
        return loop.run_until_complete(awaitable)

    def _apply_full_context_draft_reevaluation(
        self,
        run: GraphRun,
        draft: RecordDraft,
        prompt: str,
        actor: UserContext,
    ) -> list[str] | None:
        before_payload = self._json_safe(draft.payload)
        envelope = self._reevaluation_envelope(run, draft, prompt, actor)
        result = self.extractor.reevaluate_payload_patch_with_metadata(envelope)
        patch = result.patch
        payload_patch = self._unwrap_payload_patch(patch.payload_patch)
        if result.provider_used == "Heuristic" or not payload_patch:
            if result.warnings or result.provider_fallbacks:
                draft.warnings = list(dict.fromkeys([*draft.warnings, *result.warnings, *result.provider_fallbacks]))
            return None

        try:
            next_payload = self._json_safe(draft.payload)
            self._merge_payload_patch(next_payload, payload_patch)
            self._preserve_canonical_source_fields(next_payload, before_payload)
            draft.payload = next_payload
            draft.payload["operator_prompt"] = prompt
            draft.payload["operator_prompt_history"] = [*draft.payload.get("operator_prompt_history", []), prompt]
            draft.payload["revision_count"] = int(draft.payload.get("revision_count") or 0) + 1
            draft.payload["provider_used"] = result.provider_used
            draft.payload["provider_fallbacks"] = result.provider_fallbacks
            draft.payload["parse_warnings"] = list(dict.fromkeys([*result.warnings, *patch.warnings]))
            draft.payload["schema_validated"] = True
            draft.payload["extraction_mode"] = "full_context_reevaluation"
            if patch.reasoning_summary:
                draft.payload["reevaluation_reasoning_summary"] = patch.reasoning_summary
            self._validate_draft_payload_after_patch(run, draft)
            self._clear_stale_geos_after_location_edits(draft, before_payload)
            self._refresh_draft_display(draft)
            self._enrich_drafts_with_geocodes([draft])
            after_payload = self._json_safe(draft.payload)
            changed_fields = list(
                dict.fromkeys(
                    [
                        *patch.changed_fields,
                        *self._changed_payload_paths(before_payload, after_payload),
                    ]
                )
            )
            draft.changed_fields = list(dict.fromkeys([*draft.changed_fields, *changed_fields]))
            draft.warnings = list(
                dict.fromkeys(
                    [
                        *draft.warnings,
                        *result.warnings,
                        *patch.warnings,
                        "Reevaluated with full draft context.",
                    ]
                )
            )
            return changed_fields
        except Exception as exc:
            draft.payload = before_payload
            draft.warnings = list(
                dict.fromkeys(
                    [
                        *draft.warnings,
                        f"Model reevaluation patch was rejected during validation: {exc.__class__.__name__}.",
                    ]
                )
            )
            return None

    def _reevaluation_envelope(
        self,
        run: GraphRun,
        draft: RecordDraft,
        prompt: str,
        actor: UserContext,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "graph_name": run.graph_name,
            "run_status": run.status.value,
            "draft_type": draft.draft_type.value,
            "operator_prompt": prompt,
            "actor": {
                "uid": actor.uid,
                "active_org_id": actor.active_org_id,
                "active_org_role": actor.active_org_role.value if actor.active_org_role else None,
            },
            "draft": self._compact_for_model(
                {
                    "draft_id": draft.draft_id,
                    "title": draft.title,
                    "payload": draft.payload,
                    "display_fields": draft.display_fields,
                    "confidence": draft.confidence,
                    "warnings": draft.warnings,
                    "changed_fields": draft.changed_fields,
                    "source_fragment": draft.source_fragment,
                    "source_row_index": draft.source_row_index,
                    "source_headers": draft.source_headers,
                    "normalization_trace": draft.normalization_trace,
                    "map_status": draft.map_status.value,
                    "geo_resolution_status": draft.geo_resolution_status,
                },
                depth=6,
            ),
            "source_artifacts": self._compact_for_model(
                [
                    {
                        "source_kind": artifact.source_kind,
                        "filename": artifact.filename,
                        "text": artifact.text,
                        "parse_status": artifact.parse_status,
                        "parse_warnings": artifact.parse_warnings,
                    }
                    for artifact in run.source_artifacts[:2]
                ],
                depth=4,
            ),
            "repository_context": self._operator_context(run.org_id),
            **(extra or {}),
        }

    def _operator_context(self, org_id: str) -> dict[str, Any]:
        cases = [
            {
                "case_id": case.case_id,
                "status": case.status.value,
                "urgency": case.urgency.value,
                "location_text": case.location_text,
                "geo": case.geo.model_dump(mode="json") if case.geo else None,
                "summary": self._truncate_text(case.raw_input, 260),
            }
            for case in self.repository.list_cases()
            if case.org_id == org_id
        ][:20]
        teams = [
            {
                "team_id": team.team_id,
                "display_name": team.display_name,
                "capability_tags": team.capability_tags,
                "availability_status": team.availability_status.value,
                "base_geo": team.base_geo.model_dump(mode="json") if team.base_geo else None,
                "current_geo": team.current_geo.model_dump(mode="json") if team.current_geo else None,
            }
            for team in self.repository.list_teams()
            if team.org_id == org_id
        ][:30]
        resources = [
            {
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "quantity_available": resource.quantity_available,
                "location": resource.location.model_dump(mode="json") if resource.location else None,
                "current_geo": resource.current_geo.model_dump(mode="json") if resource.current_geo else None,
            }
            for resource in self.repository.list_resources()
            if resource.org_id == org_id
        ][:30]
        return {"cases": cases, "teams": teams, "resources": resources}

    def _compact_for_model(self, value: Any, depth: int = 5) -> Any:
        if depth <= 0:
            if isinstance(value, str):
                return self._truncate_text(value, 280)
            if isinstance(value, (int, float, bool)) or value is None:
                return value
            return str(type(value).__name__)
        if isinstance(value, dict):
            return {str(key): self._compact_for_model(item, depth - 1) for key, item in list(value.items())[:80]}
        if isinstance(value, list):
            return [self._compact_for_model(item, depth - 1) for item in value[:40]]
        if isinstance(value, str):
            return self._truncate_text(value, 1500)
        return value

    def _merge_payload_patch(self, target: dict[str, Any], patch: dict[str, Any]) -> None:
        immutable_keys = {"source_raw_input", "raw_input", "source_row", "original_source_row", "source_fragment", "source_headers"}
        for key, value in patch.items():
            if key in immutable_keys:
                continue
            if "." in key:
                root = key.split(".", 1)[0]
                if root in immutable_keys:
                    continue
                self._set_path(target, key.split("."), self._coerce_patch_value(key, value))
                continue
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._merge_payload_patch(target[key], value)
            else:
                target[key] = self._coerce_patch_value(key, value)

    def _unwrap_payload_patch(self, payload_patch: dict[str, Any]) -> dict[str, Any]:
        if set(payload_patch.keys()) == {"payload"} and isinstance(payload_patch.get("payload"), dict):
            return payload_patch["payload"]
        return payload_patch

    def _coerce_patch_value(self, path: str, value: Any) -> Any:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"null", "none"}:
                return None
            if path.endswith(("lat", "lng", "quantity_available", "service_radius_km", "reliability_score", "people_affected", "time_to_act_hours", "confidence", "active_dispatches", "match_score", "eta_minutes")):
                try:
                    parsed = float(value)
                    if path.endswith(("people_affected", "active_dispatches", "eta_minutes")):
                        return int(parsed)
                    return parsed
                except ValueError:
                    return value
        return value

    def _preserve_canonical_source_fields(self, payload: dict[str, Any], before_payload: dict[str, Any]) -> None:
        for key in ("source_raw_input", "raw_input", "source_row", "original_source_row", "source_fragment", "source_headers"):
            if key in before_payload:
                payload[key] = before_payload[key]

    def _validate_draft_payload_after_patch(self, run: GraphRun, draft: RecordDraft) -> None:
        if draft.draft_type == DraftRecordType.INCIDENT:
            extraction = IncidentExtraction.model_validate(draft.payload.get("extracted"))
            geo_payload = draft.payload.get("geo")
            if isinstance(geo_payload, dict):
                draft.payload["geo"] = GeoPoint.model_validate(geo_payload).model_dump(mode="json")
                draft.payload["location_confidence"] = str(draft.payload.get("location_confidence") or LocationConfidence.EXACT.value)
            draft.confidence = extraction.confidence
            return
        if draft.draft_type == DraftRecordType.TEAM:
            team = Team.model_validate(draft.payload.get("team"))
            draft.payload["team"] = team.model_dump(mode="json")
            draft.confidence = min(1.0, draft.confidence + 0.03)
            return
        if draft.draft_type == DraftRecordType.RESOURCE:
            resource = ResourceInventory.model_validate(draft.payload.get("resource"))
            draft.payload["resource"] = resource.model_dump(mode="json")
            draft.confidence = min(1.0, draft.confidence + 0.03)
            return
        if draft.draft_type == DraftRecordType.DISPATCH:
            if isinstance(draft.payload.get("batch_plan"), dict):
                plan = BatchDispatchPlan.model_validate(draft.payload["batch_plan"])
                self._refresh_batch_plan_summary(plan)
                draft.payload["batch_plan"] = plan.model_dump(mode="json")
            else:
                self._validate_single_dispatch_payload(run, draft.payload)
            draft.confidence = min(1.0, draft.confidence + 0.03)

    def _validate_single_dispatch_payload(self, run: GraphRun, payload: dict[str, Any]) -> None:
        recommendations = [
            Recommendation.model_validate(item).model_dump(mode="json")
            for item in payload.get("recommendations", [])
            if isinstance(item, dict)
        ]
        ranked = [
            Recommendation.model_validate(item).model_dump(mode="json")
            for item in payload.get("ranked_recommendations", recommendations)
            if isinstance(item, dict)
        ]
        reserves = [
            Recommendation.model_validate(item).model_dump(mode="json")
            for item in payload.get("reserve_teams", [])
            if isinstance(item, dict)
        ]
        selected = payload.get("selected_plan")
        if isinstance(selected, dict):
            selected = Recommendation.model_validate(selected).model_dump(mode="json")
        elif ranked:
            selected = ranked[0]
        else:
            selected = None
        payload["recommendations"] = recommendations or ranked
        payload["ranked_recommendations"] = ranked or recommendations
        payload["reserve_teams"] = reserves
        payload["selected_plan"] = selected
        self._recompute_single_dispatch_routes(run, payload)

    def _recompute_single_dispatch_routes(self, run: GraphRun, payload: dict[str, Any]) -> None:
        destination = self._dispatch_destination_geo(payload)
        team_map = {team.team_id: team for team in self.repository.list_teams() if team.org_id == run.org_id}

        def refresh(item: dict[str, Any] | None) -> None:
            if not isinstance(item, dict):
                return
            team = team_map.get(str(item.get("team_id") or ""))
            origin = (team.current_geo or team.base_geo) if team else None
            try:
                route = self.routing.route_sync(origin, destination)
            except Exception:
                route = None
            if route is not None:
                item["route_summary"] = route.model_dump(mode="json")
                item["eta_minutes"] = route.duration_minutes

        for key in ("recommendations", "ranked_recommendations", "reserve_teams"):
            for item in payload.get(key, []) if isinstance(payload.get(key), list) else []:
                refresh(item)
        refresh(payload.get("selected_plan") if isinstance(payload.get("selected_plan"), dict) else None)

    def _dispatch_destination_geo(self, payload: dict[str, Any]) -> GeoPoint | None:
        override = payload.get("location_override") or payload.get("case_location_override")
        if isinstance(override, dict):
            geo_payload = override.get("geo") or override.get("location")
            if isinstance(geo_payload, dict):
                try:
                    return GeoPoint.model_validate(geo_payload)
                except Exception:
                    pass
            lat = override.get("lat")
            lng = override.get("lng")
            if isinstance(lat, int | float) and isinstance(lng, int | float):
                return GeoPoint(lat=float(lat), lng=float(lng))
        case_id = payload.get("case_id")
        if case_id:
            try:
                case = self.repository.get_case(str(case_id))
                return case.geo
            except Exception:
                return None
        return None

    def _reevaluate_incident_draft(self, draft: RecordDraft, prompt: str) -> None:
        source_raw_input = str(draft.payload.get("source_raw_input") or draft.payload.get("raw_input") or draft.title)
        previous = draft.payload.get("extracted") if isinstance(draft.payload.get("extracted"), dict) else None
        result = self.extractor.reevaluate_incident(source_raw_input, prompt, previous)
        extraction = result.extraction
        previous_geo = draft.payload.get("geo")
        previous_location_confidence = draft.payload.get("location_confidence", "UNKNOWN")
        previous_location_text = str((previous or {}).get("location_text") or "")
        location_changed = previous_location_text != extraction.location_text
        draft.title = f"{extraction.category} - {extraction.location_text or 'Location pending'}"
        history = [*draft.payload.get("operator_prompt_history", []), prompt]
        draft.payload.update(
            {
                "source_raw_input": source_raw_input,
                "working_input": self._prune_and_redact(f"{source_raw_input}\nOperator correction: {prompt}"),
                "raw_input": source_raw_input,
                "extracted": extraction.model_dump(mode="json"),
                "geo": None if location_changed else previous_geo,
                "location_confidence": (
                    ("UNKNOWN" if extraction.data_quality.missing_location else "APPROXIMATE")
                    if location_changed or not previous_geo
                    else previous_location_confidence
                ),
                "geo_resolution_status": "pending" if location_changed else draft.payload.get("geo_resolution_status", "pending"),
                "operator_prompt": prompt,
                "operator_prompt_history": history,
                "revision_count": int(draft.payload.get("revision_count") or 0) + 1,
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
        self._refresh_draft_display(draft)

    def _reevaluate_team_draft(self, draft: RecordDraft, prompt: str) -> None:
        source_text = str(draft.payload.get("source_raw_input") or draft.payload.get("working_input") or draft.payload.get("raw_input") or draft.title)
        previous_team = dict(draft.payload.get("team") or {})
        patched_row = self._team_to_row(Team.model_validate(previous_team))
        patched_row.update(self._stringify_values(draft.payload.get("source_row") or {}))
        prompt_patched_keys = self._apply_prompt_patch_to_row(patched_row, prompt, "teams")
        try:
            result = self.extractor.reevaluate_team(source_text, prompt, previous_team)
            payload = result.batch.teams[0] if result.batch.teams else None
            if payload is None:
                raise ValueError("No team returned by reevaluation model.")
            existing = Team.model_validate(previous_team)
            base_label = self._prompt_or_model_value("base_label", prompt_patched_keys, patched_row, payload.base_label) or existing.base_label
            current_label = (
                self._prompt_or_model_value("current_label", prompt_patched_keys, patched_row, payload.current_label)
                or base_label
                or existing.current_label
            )
            patched_base_geo = (self._geo_from_row(patched_row, "base") if {"base_lat", "base_lng"} & prompt_patched_keys else None) or payload.base_geo or self._geo_from_row(patched_row, "base") or self._geo_from_row(patched_row)
            patched_current_geo = (self._geo_from_row(patched_row, "current") if {"current_lat", "current_lng"} & prompt_patched_keys else None) or payload.current_geo or self._geo_from_row(patched_row, "current")
            base_geo = patched_base_geo or (existing.base_geo if base_label == existing.base_label else None)
            current_geo = patched_current_geo or base_geo or (
                existing.current_geo if current_label == existing.current_label else None
            )
            active_dispatches = (
                self._parse_int(patched_row.get("active_dispatches"), existing.active_dispatches)
                if "active_dispatches" in prompt_patched_keys
                else (payload.active_dispatches if payload.active_dispatches is not None else existing.active_dispatches)
            )
            service_radius = (
                self._parse_float(patched_row.get("service_radius_km"), existing.service_radius_km)
                if "service_radius_km" in prompt_patched_keys
                else (payload.service_radius_km if payload.service_radius_km is not None else existing.service_radius_km)
            )
            reliability = (
                self._parse_float(patched_row.get("reliability_score"), existing.reliability_score)
                if "reliability_score" in prompt_patched_keys
                else (payload.reliability_score if payload.reliability_score is not None else existing.reliability_score)
            )
            team = Team(
                team_id=self._prompt_or_model_value("team_id", prompt_patched_keys, patched_row, payload.team_id) or existing.team_id,
                org_id=existing.org_id,
                display_name=self._prompt_or_model_value("display_name", prompt_patched_keys, patched_row, payload.display_name) or existing.display_name,
                capability_tags=(
                    self._split_tags(patched_row.get("capability_tags"))
                    if "capability_tags" in prompt_patched_keys
                    else [item.upper().replace(" ", "_") for item in payload.capability_tags]
                ) or existing.capability_tags,
                member_ids=(self._split_tags(patched_row.get("member_ids")) if "member_ids" in prompt_patched_keys else payload.member_ids) or existing.member_ids,
                service_radius_km=service_radius,
                base_label=base_label,
                base_geo=base_geo,
                current_label=current_label,
                current_geo=current_geo,
                availability_status=self._availability(patched_row.get("availability_status")) if "availability_status" in prompt_patched_keys else (payload.availability_status or existing.availability_status),
                active_dispatches=active_dispatches,
                reliability_score=reliability,
                evidence_ids=(self._split_tags(patched_row.get("evidence_ids")) if "evidence_ids" in prompt_patched_keys else payload.evidence_ids) or existing.evidence_ids,
                notes=list(dict.fromkeys([*existing.notes, *payload.notes, prompt])),
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )
            updated = self._team_draft_from_team(team, source_text, prompt, draft.source_row_index, result.provider_used)
            updated.payload["provider_fallbacks"] = result.provider_fallbacks
            updated.payload["parse_warnings"] = result.warnings
            updated.payload["source_raw_input"] = source_text
            updated.payload["working_input"] = self._prune_and_redact(f"{source_text}\nOperator correction: {prompt}")
            updated.payload["source_row"] = draft.payload.get("source_row")
            updated.payload["operator_prompt_history"] = [*(draft.payload.get("operator_prompt_history") or []), prompt]
            updated.payload["revision_count"] = int(draft.payload.get("revision_count", 0)) + 1
            updated.payload["extraction_mode"] = "model_reevaluation" if result.provider_used != "Heuristic" else "heuristic_reevaluation"
            self._copy_replacement_draft(draft, updated)
            draft.warnings = list(dict.fromkeys([*updated.warnings, *result.warnings, f"Reevaluated with operator prompt: {prompt}"]))
            draft.changed_fields = list(dict.fromkeys([*draft.changed_fields, "team"]))
        except Exception:
            notes = str(patched_row.get("notes") or draft.payload.get("raw_input") or "")
            patched_row["notes"] = self._prune_and_redact(f"{notes}\nOperator correction: {prompt}")
            updated = self._team_draft_from_row(patched_row, prompt)
            self._copy_replacement_draft(draft, updated)
            draft.warnings = [*updated.warnings, f"Reevaluated with deterministic prompt patch: {prompt}"]

    def _reevaluate_resource_draft(self, draft: RecordDraft, prompt: str) -> None:
        source_text = str(draft.payload.get("source_raw_input") or draft.payload.get("working_input") or draft.payload.get("raw_input") or draft.title)
        previous_resource = dict(draft.payload.get("resource") or {})
        patched_row = self._resource_to_row(ResourceInventory.model_validate(previous_resource))
        patched_row.update(self._stringify_values(draft.payload.get("source_row") or {}))
        prompt_patched_keys = self._apply_prompt_patch_to_row(patched_row, prompt, "resources")
        try:
            result = self.extractor.reevaluate_resource(source_text, prompt, previous_resource)
            payload = result.batch.resources[0] if result.batch.resources else None
            if payload is None:
                raise ValueError("No resource returned by reevaluation model.")
            existing = ResourceInventory.model_validate(previous_resource)
            location_label = self._prompt_or_model_value("location_label", prompt_patched_keys, patched_row, payload.location_label) or existing.location_label
            current_label = (
                self._prompt_or_model_value("current_label", prompt_patched_keys, patched_row, payload.current_label)
                or location_label
                or existing.current_label
            )
            patched_location = (self._geo_from_row(patched_row, "location") if {"location_lat", "location_lng"} & prompt_patched_keys else None) or payload.location or self._geo_from_row(patched_row, "location") or self._geo_from_row(patched_row)
            patched_current_geo = (self._geo_from_row(patched_row, "current") if {"current_lat", "current_lng"} & prompt_patched_keys else None) or payload.current_geo or self._geo_from_row(patched_row, "current")
            location = patched_location or (existing.location if location_label == existing.location_label else None)
            current_geo = patched_current_geo or location or (
                existing.current_geo if current_label == existing.current_label else None
            )
            quantity_available = (
                self._parse_float(patched_row.get("quantity_available"), existing.quantity_available)
                if "quantity_available" in prompt_patched_keys
                else (payload.quantity_available if payload.quantity_available is not None else existing.quantity_available)
            )
            resource = ResourceInventory(
                resource_id=self._prompt_or_model_value("resource_id", prompt_patched_keys, patched_row, payload.resource_id) or existing.resource_id,
                org_id=existing.org_id,
                owning_team_id=self._prompt_or_model_value("owning_team_id", prompt_patched_keys, patched_row, payload.owning_team_id) or existing.owning_team_id,
                resource_type=(self._prompt_or_model_value("resource_type", prompt_patched_keys, patched_row, payload.resource_type) or existing.resource_type).upper().replace(" ", "_"),
                quantity_available=quantity_available,
                location_label=location_label,
                location=location,
                current_label=current_label,
                current_geo=current_geo,
                constraints=(
                    self._split_tags(patched_row.get("constraints"))
                    if "constraints" in prompt_patched_keys
                    else [item.upper().replace(" ", "_") for item in payload.constraints]
                ) or existing.constraints,
                evidence_ids=(self._split_tags(patched_row.get("evidence_ids")) if "evidence_ids" in prompt_patched_keys else payload.evidence_ids) or existing.evidence_ids,
                image_url=self._prompt_or_model_value("image_url", prompt_patched_keys, patched_row, payload.image_url) or existing.image_url,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )
            updated = self._resource_draft_from_resource(resource, source_text, prompt, draft.source_row_index, result.provider_used)
            updated.payload["provider_fallbacks"] = result.provider_fallbacks
            updated.payload["parse_warnings"] = result.warnings
            updated.payload["source_raw_input"] = source_text
            updated.payload["working_input"] = self._prune_and_redact(f"{source_text}\nOperator correction: {prompt}")
            updated.payload["source_row"] = draft.payload.get("source_row")
            updated.payload["operator_prompt_history"] = [*(draft.payload.get("operator_prompt_history") or []), prompt]
            updated.payload["revision_count"] = int(draft.payload.get("revision_count", 0)) + 1
            updated.payload["extraction_mode"] = "model_reevaluation" if result.provider_used != "Heuristic" else "heuristic_reevaluation"
            self._copy_replacement_draft(draft, updated)
            draft.warnings = list(dict.fromkeys([*updated.warnings, *result.warnings, f"Reevaluated with operator prompt: {prompt}"]))
            draft.changed_fields = list(dict.fromkeys([*draft.changed_fields, "resource"]))
        except Exception:
            notes = str(patched_row.get("notes") or draft.payload.get("raw_input") or "")
            patched_row["notes"] = self._prune_and_redact(f"{notes}\nOperator correction: {prompt}")
            updated = self._resource_draft_from_row(patched_row, prompt)
            self._copy_replacement_draft(draft, updated)
            draft.warnings = [*updated.warnings, f"Reevaluated with deterministic prompt patch: {prompt}"]

    def _reevaluate_dispatch_draft(self, draft: RecordDraft, prompt: str) -> None:
        recommendations = list(draft.payload.get("ranked_recommendations") or draft.payload.get("recommendations") or [])
        reserves = list(draft.payload.get("reserve_teams") or [])
        conflicts = list(draft.payload.get("conflicts") or [])
        lowered = prompt.lower()

        excluded_team_ids = []
        for recommendation in [*recommendations, *reserves]:
            if not isinstance(recommendation, dict):
                continue
            team_id = str(recommendation.get("team_id") or "")
            if team_id and team_id.lower() in lowered and any(token in lowered for token in ("exclude", "avoid", "do not use", "don't use")):
                excluded_team_ids.append(team_id)

        if excluded_team_ids:
            recommendations = [
                item
                for item in recommendations
                if not (isinstance(item, dict) and item.get("team_id") in excluded_team_ids)
            ]
            reserves = [
                item
                for item in reserves
                if not (isinstance(item, dict) and item.get("team_id") in excluded_team_ids)
            ]
            conflicts.append(f"Operator excluded team(s): {', '.join(excluded_team_ids)}.")

        if "reserve" in lowered and not reserves and len(recommendations) > 1:
            reserves = recommendations[1:2]
            recommendations = recommendations[:1]
            conflicts.append("Operator requested reserve capacity; second-ranked option moved to reserve.")

        selected_plan = recommendations[0] if recommendations else None
        draft.payload.update(
            {
                "operator_prompt": prompt,
                "operator_prompt_history": [*draft.payload.get("operator_prompt_history", []), prompt],
                "revision_count": int(draft.payload.get("revision_count") or 0) + 1,
                "recommendations": recommendations,
                "ranked_recommendations": recommendations,
                "selected_plan": selected_plan,
                "reserve_teams": reserves,
                "conflicts": list(dict.fromkeys(str(item) for item in conflicts)),
                "reasoning_summary": self._dispatch_reasoning_summary_dicts(recommendations, reserves, conflicts, draft.payload.get("unassigned_reason")),
            }
        )
        draft.confidence = 0.82 if recommendations else 0.35
        draft.warnings = list(dict.fromkeys([*draft.warnings, f"Reevaluated dispatch plan with operator prompt: {prompt}", *conflicts]))

    def _dispatch_reasoning_summary_dicts(
        self,
        recommendations: list[Any],
        reserves: list[Any],
        conflicts: list[Any],
        reason: Any,
    ) -> str:
        if not recommendations:
            return str(reason or "No feasible dispatch option found.")
        top = recommendations[0] if isinstance(recommendations[0], dict) else {}
        team_id = top.get("team_id") if isinstance(top, dict) else None
        eta = top.get("eta_minutes") if isinstance(top, dict) else None
        score = top.get("match_score") if isinstance(top, dict) else 0
        reserve_text = f" {len(reserves)} reserve option(s) retained." if reserves else ""
        conflict_text = f" {len(conflicts)} warning(s) require operator awareness." if conflicts else ""
        return f"Selected {team_id or 'top available team'} with match score {float(score or 0):.2f} and ETA {eta if eta is not None else 'unknown'} minutes.{reserve_text}{conflict_text}"

    def _canonicalize_csv_row(self, row: dict[str, str]) -> dict[str, str]:
        canonical = dict(row)
        lookup: dict[str, str] = {}
        for key, value in row.items():
            normalized = self._normalize_csv_key(key)
            if value and normalized not in lookup:
                lookup[normalized] = value

        def first(*names: str) -> str:
            for name in names:
                value = lookup.get(self._normalize_csv_key(name))
                if value:
                    return value
            return ""

        title = first("title", "headline", "event_title")
        summary = first("summary", "description", "details", "message", "report", "content", "incident_description", "event_description")
        event_type = first("event_type", "event type", "hazard_type", "hazard", "disaster_type", "disaster", "type")
        country = first("country", "country_name", "admin0", "state", "province", "district", "region", "area")
        location = first(
            "location_text",
            "location",
            "address",
            "site",
            "village",
            "district",
            "block",
            "ward",
            "camp",
            "facility",
            "hospital",
            "warehouse_address",
            "depot_address",
            "base_address",
            "current_address",
            "place",
            "event_location",
            "affected_area",
            "area_name",
            "city",
            "admin_area",
        )
        if not location and country:
            location = country
        if not location and title:
            match = re.search(r"\bin\s+([^,.;]+(?:,\s*[^,.;]+)?)", title, flags=re.IGNORECASE)
            if match:
                location = match.group(1).strip()

        raw_parts = [part for part in (title, summary) if part]
        if event_type:
            raw_parts.append(f"Event type: {event_type}")
        if country and country not in " ".join(raw_parts):
            raw_parts.append(f"Country/Admin area: {country}")
        if location and location not in " ".join(raw_parts):
            raw_parts.append(f"Location: {location}")

        aliases = {
            "source_id": first("id", "event_id", "source_id", "gdacs_id"),
            "raw_input": first("raw_input", "incident", "case", "report_text") or "\n".join(raw_parts),
            "description": summary,
            "summary": summary,
            "title": title,
            "event_type": event_type,
            "hazard_type": event_type or first("hazard_type", "hazard"),
            "location_text": location,
            "lat": first("lat", "latitude", "geo_lat", "geo latitude", "y"),
            "lng": first("lng", "lon", "long", "longitude", "geo_long", "geo_lon", "geo longitude", "x"),
            "country": country,
            "iso3": first("iso3", "country_code", "iso"),
            "severity_value": first("severity_value", "severity", "magnitude", "mag", "intensity", "alert_score"),
            "severity_unit": first("severity_unit", "severity unit", "magnitude_unit", "unit"),
            "source": first("source", "provider", "origin"),
            "link": first("link", "url", "source_url", "report_url"),
            "reported_at": first("reported_at", "from_date", "start_date", "date", "event_date", "created_at", "time"),
            "due_by": first("due_by", "to_date", "end_date", "valid_until"),
            "source_confidence": first("source_confidence", "confidence", "alert_level", "alert", "gdacs_alert"),
            "map_feature": first("map_feature", "gdacs_bbox", "bbox", "geometry", "geodata"),
            "people_affected": first("people_affected", "population_affected", "affected_people", "affected", "population"),
            "base_label": first("base_label", "base", "base_address", "station", "station_address", "site", "location", "address", "village", "district"),
            "current_label": first("current_label", "current_location", "current_address", "site", "location", "address", "village", "district"),
            "location_label": first("location_label", "warehouse", "depot", "warehouse_address", "depot_address", "site", "location", "address", "village", "district"),
            "display_name": first("display_name", "team_name", "unit", "crew", "group", "name"),
            "capability_tags": first("capability_tags", "capabilities", "skills", "abilities", "certifications"),
            "availability_status": first("availability_status", "availability", "status"),
            "resource_type": first("resource_type", "asset", "item", "stock_type", "supply", "equipment", "category"),
            "quantity_available": first("quantity_available", "quantity", "count", "stock", "available"),
        }
        for key, value in aliases.items():
            if value and not canonical.get(key):
                canonical[key] = value

        if not canonical.get("source_confidence") and title:
            alert_match = re.match(r"\s*(red|orange|green)\b", title, flags=re.IGNORECASE)
            if alert_match:
                canonical["source_confidence"] = alert_match.group(1).upper()

        if not canonical.get("category") and event_type:
            canonical["category"] = self._category_from_event_type(event_type).value
        if not canonical.get("required_resources") and event_type:
            canonical["required_resources"] = ",".join(self._resources_for_event_type(event_type))
        return canonical

    def _normalize_csv_key(self, key: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")

    def _row_matches_target(self, row: dict[str, str], target: str) -> bool:
        keys = {self._normalize_csv_key(key) for key, value in row.items() if str(value or "").strip()}
        values_text = " ".join(str(value or "") for value in row.values()).lower()
        incident_keys = {
            "raw_input",
            "description",
            "summary",
            "title",
            "incident",
            "case",
            "event_type",
            "hazard_type",
            "disaster_type",
            "category",
            "location_text",
            "required_resources",
            "severity",
            "severity_value",
            "severity_unit",
            "reported_at",
            "from_date",
            "to_date",
            "geo_lat",
            "geo_long",
            "gdacs_bbox",
            "source",
            "link",
        }
        team_keys = {"team_id", "display_name", "team_name", "unit", "crew", "name", "capability_tags", "skills", "abilities", "capabilities", "base_label", "base_address", "station", "member_ids", "service_radius_km", "availability", "certifications"}
        resource_keys = {"resource_id", "resource_type", "asset", "stock_type", "item", "category", "quantity_available", "quantity", "count", "stock", "location_label", "owning_team_id", "owner_team_id", "constraints", "warehouse", "depot", "site"}
        incident_terms = {
            "earthquake",
            "wildfire",
            "forest fire",
            "flood",
            "cyclone",
            "storm",
            "volcano",
            "landslide",
            "drought",
            "epidemic",
            "disaster",
            "emergency",
            "evacuation",
            "affected",
            "magnitude",
        }
        if target == "teams":
            return len(keys & team_keys) >= 2 or ("team" in values_text and bool(keys & {"skills", "capabilities", "base_label", "location_text"}))
        if target == "resources":
            return len(keys & resource_keys) >= 2 or ("stock" in values_text and bool(keys & {"quantity", "location_text", "warehouse", "depot"}))
        if target in {"mixed", "all"}:
            return self._row_matches_target(row, "incidents") or self._row_matches_target(row, "teams") or self._row_matches_target(row, "resources")
        incident_score = len(keys & incident_keys)
        if any(term in values_text for term in incident_terms):
            incident_score += 2
        if keys & {"geo_lat", "geo_long", "lat", "lng", "latitude", "longitude"}:
            incident_score += 1
        return incident_score >= 2

    def _category_from_event_type(self, event_type: str) -> CategoryKind:
        lowered = event_type.lower()
        if any(token in lowered for token in ("earthquake", "flood", "cyclone", "storm", "landslide", "tsunami")):
            return CategoryKind.RESCUE
        if any(token in lowered for token in ("wildfire", "forest fire", "fire", "volcano")):
            return CategoryKind.PROTECTION
        if any(token in lowered for token in ("drought", "water shortage")):
            return CategoryKind.WATER
        if any(token in lowered for token in ("epidemic", "disease", "health")):
            return CategoryKind.MEDICAL
        return CategoryKind.LOGISTICS

    def _resources_for_event_type(self, event_type: str) -> list[str]:
        lowered = event_type.lower()
        if any(token in lowered for token in ("wildfire", "forest fire", "fire", "volcano")):
            return ["FIRE_EXTINGUISHER", "N95_MASKS"]
        if any(token in lowered for token in ("earthquake", "landslide")):
            return ["SEARCH_AND_RESCUE_TEAM", "MEDICAL_KIT"]
        if any(token in lowered for token in ("flood", "tsunami")):
            return ["RESCUE_BOAT", "WATER_RESCUE_TEAM"]
        if any(token in lowered for token in ("cyclone", "storm")):
            return ["SHELTER_KIT", "RESCUE_TEAM"]
        if any(token in lowered for token in ("drought", "water shortage")):
            return ["WATER_TANKER"]
        if any(token in lowered for token in ("epidemic", "disease", "health")):
            return ["MEDICAL_KIT"]
        return []

    def _resource_needs_from_value(self, value: str | None) -> list[ResourceNeed]:
        return [
            ResourceNeed(resource_type=resource_type, quantity=None, unit=None)
            for resource_type in self._split_tags(value)
        ]

    def _parse_people_affected(self, value: str | None) -> int | None:
        if not value:
            return None
        text = value.lower().replace(",", "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*(million|m|thousand|k)?\s+(?:people|persons|affected|in mmi)", text)
        if not match:
            match = re.search(r"(?:people|persons|affected|population)\D{0,16}(\d+(?:\.\d+)?)\s*(million|m|thousand|k)?", text)
        if not match:
            return None
        number = float(match.group(1))
        suffix = match.group(2) or ""
        if suffix in {"million", "m"}:
            number *= 1_000_000
        elif suffix in {"thousand", "k"}:
            number *= 1_000
        return int(number)

    def _urgency_from_row(self, row: dict[str, str]) -> UrgencyKind | None:
        alert = (row.get("source_confidence") or row.get("alert_level") or "").lower()
        if "red" in alert:
            return UrgencyKind.CRITICAL
        if "orange" in alert:
            return UrgencyKind.HIGH
        if "green" in alert:
            return UrgencyKind.LOW
        severity = self._parse_float(row.get("severity_value"), -1)
        unit = (row.get("severity_unit") or row.get("event_type") or "").lower()
        if severity < 0:
            return None
        if unit.strip() == "m" or "earthquake" in unit:
            if severity >= 7:
                return UrgencyKind.CRITICAL
            if severity >= 5.5:
                return UrgencyKind.HIGH
            return UrgencyKind.MEDIUM
        if "ha" in unit or "wildfire" in unit or "fire" in unit:
            if severity >= 10000:
                return UrgencyKind.HIGH
            if severity >= 1000:
                return UrgencyKind.MEDIUM
            return UrgencyKind.LOW
        return None

    def _apply_prompt_patch_to_row(self, row: dict[str, str], prompt: str, target: str) -> set[str]:
        patched: set[str] = set()
        if target == "teams":
            team_id = self._extract_prompt_value(prompt, ["team id", "team_id", "id"])
            name = self._extract_prompt_value(prompt, ["name", "team name", "display name"])
            location = self._extract_prompt_value(prompt, ["location", "base", "base label"])
            current_location = self._extract_prompt_value(prompt, ["current location", "current", "current label"])
            capabilities = self._extract_prompt_value(prompt, ["capabilities", "capability", "skills"])
            members = self._extract_prompt_value(prompt, ["members", "member ids", "member_ids"])
            status = self._extract_prompt_value(prompt, ["availability", "availability status", "status"])
            notes = self._extract_prompt_value(prompt, ["notes", "note"])
            radius = self._extract_prompt_number(prompt, ["radius", "service radius"])
            reliability = self._extract_prompt_number(prompt, ["reliability", "reliability score"])
            active_dispatches = self._extract_prompt_number(prompt, ["active dispatches", "active_dispatches", "active assignments"])
            base_lat = self._extract_prompt_number(prompt, ["base lat", "base latitude", "lat", "latitude"])
            base_lng = self._extract_prompt_number(prompt, ["base lng", "base lon", "base longitude", "lng", "longitude"])
            current_lat = self._extract_prompt_number(prompt, ["current lat", "current latitude"])
            current_lng = self._extract_prompt_number(prompt, ["current lng", "current lon", "current longitude"])
            if team_id:
                row["team_id"] = team_id
                patched.add("team_id")
            if name:
                row["display_name"] = name
                patched.add("display_name")
            if location:
                row["base_label"] = location
                patched.add("base_label")
            if current_location:
                row["current_label"] = current_location
                patched.add("current_label")
            if capabilities:
                row["capability_tags"] = capabilities
                patched.add("capability_tags")
            if members:
                row["member_ids"] = members
                patched.add("member_ids")
            if status:
                row["availability_status"] = status
                patched.add("availability_status")
            if radius is not None:
                row["service_radius_km"] = str(radius)
                patched.add("service_radius_km")
            if reliability is not None:
                row["reliability_score"] = str(reliability)
                patched.add("reliability_score")
            if active_dispatches is not None:
                row["active_dispatches"] = str(active_dispatches)
                patched.add("active_dispatches")
            if notes:
                row["notes"] = notes
                patched.add("notes")
            if base_lat is not None:
                row["base_lat"] = str(base_lat)
                patched.add("base_lat")
            if base_lng is not None:
                row["base_lng"] = str(base_lng)
                patched.add("base_lng")
            if current_lat is not None:
                row["current_lat"] = str(current_lat)
                patched.add("current_lat")
            if current_lng is not None:
                row["current_lng"] = str(current_lng)
                patched.add("current_lng")
        elif target == "resources":
            resource_id = self._extract_prompt_value(prompt, ["resource id", "resource_id", "id"])
            owner = self._extract_prompt_value(prompt, ["owning team", "owning team id", "owning_team_id", "team id"])
            resource_type = self._extract_prompt_value(prompt, ["resource type", "type", "name"])
            location = self._extract_prompt_value(prompt, ["location", "depot", "warehouse"])
            current_location = self._extract_prompt_value(prompt, ["current location", "current", "current label"])
            constraints = self._extract_prompt_value(prompt, ["constraints", "constraint"])
            image_url = self._extract_prompt_value(prompt, ["image url", "image", "photo url"])
            quantity = self._extract_prompt_number(prompt, ["quantity", "stock", "count"])
            location_lat = self._extract_prompt_number(prompt, ["location lat", "location latitude", "lat", "latitude"])
            location_lng = self._extract_prompt_number(prompt, ["location lng", "location lon", "location longitude", "lng", "longitude"])
            current_lat = self._extract_prompt_number(prompt, ["current lat", "current latitude"])
            current_lng = self._extract_prompt_number(prompt, ["current lng", "current lon", "current longitude"])
            if resource_id:
                row["resource_id"] = resource_id
                patched.add("resource_id")
            if owner:
                row["owning_team_id"] = owner
                patched.add("owning_team_id")
            if resource_type:
                row["resource_type"] = resource_type
                patched.add("resource_type")
            if location:
                row["location_label"] = location
                patched.add("location_label")
            if current_location:
                row["current_label"] = current_location
                patched.add("current_label")
            if constraints:
                row["constraints"] = constraints
                patched.add("constraints")
            if quantity is not None:
                row["quantity_available"] = str(quantity)
                patched.add("quantity_available")
            if image_url:
                row["image_url"] = image_url
                patched.add("image_url")
            if location_lat is not None:
                row["location_lat"] = str(location_lat)
                patched.add("location_lat")
            if location_lng is not None:
                row["location_lng"] = str(location_lng)
                patched.add("location_lng")
            if current_lat is not None:
                row["current_lat"] = str(current_lat)
                patched.add("current_lat")
            if current_lng is not None:
                row["current_lng"] = str(current_lng)
                patched.add("current_lng")
        return patched

    def _apply_prompt_patch_to_draft(self, draft, prompt: str) -> list[str]:
        changed = []

        lat_match = re.search(r"\b(?:lat|latitude)\s*(?:to|=|:)?\s*(-?\d+(?:\.\d+)?)", prompt, re.I)
        lng_match = re.search(r"\b(?:lng|lon|longitude)\s*(?:to|=|:)?\s*(-?\d+(?:\.\d+)?)", prompt, re.I)

        lat = float(lat_match.group(1)) if lat_match else None
        lng = float(lng_match.group(1)) if lng_match else None

        if lat is None and lng is None:
            return changed

        def merge(existing):
            existing = existing or {}
            return {
                "lat": lat if lat is not None else existing.get("lat"),
                "lng": lng if lng is not None else existing.get("lng"),
            }

        if draft.draft_type == DraftRecordType.INCIDENT:
            draft.payload["geo"] = merge(draft.payload.get("geo"))
            draft.payload["location_confidence"] = "EXACT"
            draft.payload["geo_resolution_status"] = "direct_coordinates"
            changed.extend(["geo", "location_confidence", "geo_resolution_status"])

        elif draft.draft_type == DraftRecordType.TEAM:
            team = dict(draft.payload.get("team") or {})
            team["base_geo"] = merge(team.get("base_geo"))
            team["current_geo"] = merge(team.get("current_geo"))
            draft.payload["team"] = team
            draft.payload["geo_resolution_status"] = "direct_coordinates"
            changed.extend(["team.base_geo", "team.current_geo", "geo_resolution_status"])

        elif draft.draft_type == DraftRecordType.RESOURCE:
            resource = dict(draft.payload.get("resource") or {})
            resource["location"] = merge(resource.get("location"))
            resource["current_geo"] = merge(resource.get("current_geo"))
            draft.payload["resource"] = resource
            draft.payload["geo_resolution_status"] = "direct_coordinates"
            changed.extend(["resource.location", "resource.current_geo", "geo_resolution_status"])

        return changed

    def _prompt_or_model_value(
        self,
        key: str,
        prompt_patched_keys: set[str],
        patched_row: dict[str, str],
        model_value: Any,
    ) -> Any:
        if key in prompt_patched_keys:
            value = patched_row.get(key)
            return value if value != "" else None
        return model_value

    def _extract_prompt_value(self, prompt: str, labels: list[str]) -> str | None:
        for label in labels:
            if "url" in label or "image" in label or "link" in label:
                pattern = rf"{re.escape(label)}\s*(?:to|=|:)\s*([^\s;\n]+)"
            else:
                pattern = rf"{re.escape(label)}\s*(?:to|=|:)\s*([^.;\n]+)"
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(".")
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
            "domain": extraction.domain,
            "category": extraction.category,
            "subcategory": extraction.subcategory,
            "urgency": extraction.urgency,
            "location_text": extraction.location_text,
            "people_affected": extraction.people_affected,
            "vulnerable_groups": extraction.vulnerable_groups,
            "time_to_act_hours": extraction.time_to_act_hours,
            "resources": [item.model_dump(mode="json") for item in extraction.required_resources],
            "notes_for_dispatch": extraction.notes_for_dispatch,
            "data_quality": extraction.data_quality.model_dump(mode="json"),
            "confidence": extraction.confidence,
            "geo": geo.model_dump(mode="json") if geo else None,
        }

    def _team_display_fields(self, team: Team) -> dict[str, Any]:
        return {
            "team_id": team.team_id,
            "display_name": team.display_name,
            "capability_tags": team.capability_tags,
            "member_ids": team.member_ids,
            "service_radius_km": team.service_radius_km,
            "base_label": team.base_label,
            "base_geo": team.base_geo.model_dump(mode="json") if team.base_geo else None,
            "current_label": team.current_label,
            "current_geo": team.current_geo.model_dump(mode="json") if team.current_geo else None,
            "availability_status": team.availability_status,
            "active_dispatches": team.active_dispatches,
            "reliability_score": team.reliability_score,
            "evidence_ids": team.evidence_ids,
            "notes": team.notes,
            "geo": (team.current_geo or team.base_geo).model_dump(mode="json") if (team.current_geo or team.base_geo) else None,
        }

    def _resource_display_fields(self, resource: ResourceInventory) -> dict[str, Any]:
        return {
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "quantity_available": resource.quantity_available,
            "location_label": resource.location_label,
            "location": resource.location.model_dump(mode="json") if resource.location else None,
            "current_label": resource.current_label,
            "current_geo": resource.current_geo.model_dump(mode="json") if resource.current_geo else None,
            "owning_team_id": resource.owning_team_id,
            "constraints": resource.constraints,
            "evidence_ids": resource.evidence_ids,
            "image_url": resource.image_url,
            "geo": (resource.current_geo or resource.location).model_dump(mode="json") if (resource.current_geo or resource.location) else None,
        }

    def _json_safe(self, value: Any) -> Any:
        return json.loads(json.dumps(value, default=str))

    def _changed_payload_paths(self, before: Any, after: Any, prefix: str = "") -> list[str]:
        interesting_roots = {
            "extracted",
            "team",
            "resource",
            "geo",
            "location_confidence",
            "geo_resolution_status",
            "recommendations",
            "ranked_recommendations",
            "selected_plan",
            "reserve_teams",
            "conflicts",
            "reasoning_summary",
            "batch_plan",
            "case_overrides",
            "location_override",
            "case_location_override",
        }
        if prefix:
            root = prefix.split(".", 1)[0]
            if root not in interesting_roots:
                return []
        if before == after:
            return []
        if isinstance(before, dict) and isinstance(after, dict):
            changes: list[str] = []
            for key in sorted(set(before) | set(after)):
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                changes.extend(self._changed_payload_paths(before.get(key), after.get(key), next_prefix))
                if len(changes) >= 60:
                    return changes[:60]
            return changes
        if isinstance(before, list) and isinstance(after, list):
            return [prefix] if before != after and prefix else []
        return [prefix] if prefix else []

    def _clear_stale_geos_after_location_edits(self, draft: RecordDraft, before_payload: dict[str, Any]) -> None:
        try:
            if draft.draft_type == DraftRecordType.INCIDENT:
                before_extraction = before_payload.get("extracted") if isinstance(before_payload.get("extracted"), dict) else {}
                after_extraction = draft.payload.get("extracted") if isinstance(draft.payload.get("extracted"), dict) else {}
                if before_extraction.get("location_text") != after_extraction.get("location_text") and before_payload.get("geo") == draft.payload.get("geo"):
                    draft.payload["geo"] = None
                    draft.payload["location_confidence"] = (
                        LocationConfidence.UNKNOWN.value
                        if not after_extraction.get("location_text")
                        else LocationConfidence.APPROXIMATE.value
                    )
                    draft.payload["geo_resolution_status"] = "pending"
            elif draft.draft_type == DraftRecordType.TEAM:
                before_team = before_payload.get("team") if isinstance(before_payload.get("team"), dict) else {}
                team_payload = draft.payload.get("team")
                if not isinstance(team_payload, dict):
                    return
                labels_changed = any(
                    before_team.get(key) != team_payload.get(key)
                    for key in ("base_label", "current_label")
                )
                geos_unchanged = all(
                    before_team.get(key) == team_payload.get(key)
                    for key in ("base_geo", "current_geo")
                )
                if labels_changed and geos_unchanged:
                    team_payload["base_geo"] = None
                    team_payload["current_geo"] = None
                    draft.payload["geo_resolution_status"] = "pending"
            elif draft.draft_type == DraftRecordType.RESOURCE:
                before_resource = before_payload.get("resource") if isinstance(before_payload.get("resource"), dict) else {}
                resource_payload = draft.payload.get("resource")
                if not isinstance(resource_payload, dict):
                    return
                labels_changed = any(
                    before_resource.get(key) != resource_payload.get(key)
                    for key in ("location_label", "current_label")
                )
                geos_unchanged = all(
                    before_resource.get(key) == resource_payload.get(key)
                    for key in ("location", "current_geo")
                )
                if labels_changed and geos_unchanged:
                    resource_payload["location"] = None
                    resource_payload["current_geo"] = None
                    draft.payload["geo_resolution_status"] = "pending"
        except Exception:
            return

    def _apply_field_updates(self, draft: RecordDraft, updates: dict[str, Any]) -> list[str]:
        changed: list[str] = []
        for raw_path, value in updates.items():
            path = raw_path[8:] if raw_path.startswith("payload.") else raw_path
            if not path:
                continue
            self._set_path(draft.payload, path.split("."), self._coerce_field_update(path, value))
            changed.append(path)
        return changed

    def _coerce_field_update(self, path: str, value: Any) -> Any:
        if isinstance(value, str):
            if path.endswith("required_resources"):
                return [item.model_dump(mode="json") for item in self._resource_needs_from_value(value)]
            if path.endswith(("capability_tags", "constraints", "member_ids", "vulnerable_groups", "evidence_ids", "notes", "needs_followup_questions")):
                return self._split_tags(value)
            if path.endswith(("missing_location", "missing_quantity")):
                return value.strip().lower() in {"1", "true", "yes", "y", "missing"}
            if path.endswith(("lat", "lng", "quantity_available", "service_radius_km", "reliability_score", "people_affected", "time_to_act_hours", "confidence", "active_dispatches")):
                try:
                    parsed = float(value)
                    if path.endswith(("people_affected", "active_dispatches")):
                        return int(parsed)
                    return parsed
                except ValueError:
                    return value
        return value

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
            draft.geo_resolution_status = str(draft.payload.get("geo_resolution_status") or "") or draft.geo_resolution_status
            draft.extraction_mode = str(draft.payload.get("extraction_mode") or "") or draft.extraction_mode
            adapter_confidence = draft.payload.get("adapter_confidence")
            if isinstance(adapter_confidence, int | float):
                draft.adapter_confidence = float(adapter_confidence)
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

    def _copy_replacement_draft(self, target: RecordDraft, replacement: RecordDraft) -> None:
        original_id = target.draft_id
        original_headers = target.source_headers
        original_trace = target.normalization_trace
        original_fragment = target.source_fragment
        target.title = replacement.title
        target.payload = {**target.payload, **replacement.payload}
        target.confidence = min(1.0, replacement.confidence + 0.03)
        target.display_fields = replacement.display_fields
        target.map_status = replacement.map_status
        target.draft_id = original_id
        target.source_row_index = replacement.source_row_index or target.source_row_index
        target.source_headers = replacement.source_headers or original_headers
        target.normalization_trace = replacement.normalization_trace or original_trace
        target.source_fragment = replacement.source_fragment or original_fragment
        target.extraction_mode = replacement.extraction_mode
        target.adapter_confidence = replacement.adapter_confidence
        target.geo_resolution_status = replacement.geo_resolution_status

    def _team_to_row(self, team: Team) -> dict[str, str]:
        row = {
            "team_id": team.team_id,
            "display_name": team.display_name,
            "capability_tags": ",".join(team.capability_tags),
            "member_ids": ",".join(team.member_ids),
            "service_radius_km": str(team.service_radius_km),
            "base_label": team.base_label,
            "current_label": team.current_label or "",
            "availability_status": team.availability_status.value,
            "active_dispatches": str(team.active_dispatches),
            "reliability_score": str(team.reliability_score),
            "evidence_ids": ",".join(team.evidence_ids),
            "notes": " | ".join(team.notes),
        }
        if team.base_geo:
            row["base_lat"] = str(team.base_geo.lat)
            row["base_lng"] = str(team.base_geo.lng)
        if team.current_geo:
            row["current_lat"] = str(team.current_geo.lat)
            row["current_lng"] = str(team.current_geo.lng)
        return row

    def _resource_to_row(self, resource: ResourceInventory) -> dict[str, str]:
        row = {
            "resource_id": resource.resource_id,
            "owning_team_id": resource.owning_team_id or "",
            "resource_type": resource.resource_type,
            "quantity_available": str(resource.quantity_available),
            "location_label": resource.location_label,
            "current_label": resource.current_label or "",
            "constraints": ",".join(resource.constraints),
            "evidence_ids": ",".join(resource.evidence_ids),
            "image_url": resource.image_url or "",
        }
        if resource.location:
            row["location_lat"] = str(resource.location.lat)
            row["location_lng"] = str(resource.location.lng)
        if resource.current_geo:
            row["current_lat"] = str(resource.current_geo.lat)
            row["current_lng"] = str(resource.current_geo.lng)
        return row

    def _source_hash(self, record_type: str, raw: str) -> str:
        return self.duplicate_service.source_hash(record_type, raw)

    def _find_duplicate_case(self, raw_input: str, source_hash: str, org_id: str) -> Any | None:
        return self.duplicate_service.find_exact_duplicate("INCIDENT", raw_input, org_id, self.repository.list_cases())

    def _find_duplicate_team(self, team: Team, org_id: str) -> Team | None:
        fingerprint = self.duplicate_service.normalize_text(self._team_fingerprint(team))
        for existing in self.repository.list_teams():
            if existing.org_id != org_id:
                continue
            if existing.team_id == team.team_id:
                return existing
            if self.duplicate_service.normalize_text(self._team_fingerprint(existing)) == fingerprint:
                return existing
        return None

    def _find_duplicate_resource(self, resource: ResourceInventory, org_id: str) -> ResourceInventory | None:
        fingerprint = self.duplicate_service.normalize_text(self._resource_fingerprint(resource))
        for existing in self.repository.list_resources():
            if existing.org_id != org_id:
                continue
            if existing.resource_id == resource.resource_id:
                return existing
            if self.duplicate_service.normalize_text(self._resource_fingerprint(existing)) == fingerprint:
                return existing
        return None

    def _team_fingerprint(self, team: Team) -> str:
        return f"{team.display_name} {' '.join(sorted(team.capability_tags))} {team.base_label} {team.current_label or ''}"

    def _resource_fingerprint(self, resource: ResourceInventory) -> str:
        return f"{resource.resource_type} {resource.quantity_available:g} {resource.location_label} {resource.current_label or ''} {resource.owning_team_id or ''}"

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

    def _parse_int(self, value: str | None, default: int) -> int:
        parsed = self._parse_float(value, float(default))
        return max(0, int(parsed))

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
