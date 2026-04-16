from __future__ import annotations

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
    CaseEvent,
    CaseStatus,
    DraftRecordType,
    GraphRun,
    GraphRunRequest,
    GraphRunStatus,
    RecordDraft,
    SourceArtifact,
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
        draft = self._draft_from_payload(payload, state.get("cleaned_markdown", ""))
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
        if case.org_id not in {None, org_id}:
            raise PermissionError("Incident belongs to another organization.")
        questions: list[UserQuestion] = []
        if case.geo is None or case.location_confidence == "UNKNOWN":
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
        teams = [team for team in self.repository.list_teams() if team.org_id in {None, org_id}]
        volunteers = [volunteer for volunteer in self.repository.list_volunteers() if volunteer.org_id in {None, org_id}]
        resources = [resource for resource in self.repository.list_resources() if resource.org_id in {None, org_id}]
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
            run = GraphRun(
                run_id=f"run-{uuid.uuid4().hex[:10]}",
                org_id=org_id,
                graph_name="dispatch_assignment_graph",
                status=GraphRunStatus.WAITING_FOR_USER,
                created_by=actor.uid,
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

    def edit_graph_run(self, run_id: str, prompt: str, actor: UserContext, draft_id: str | None = None) -> GraphRun:
        run = self.repository.get_graph_run(run_id)
        self._require_run_org(run, actor)
        for draft in run.drafts:
            if draft_id is None or draft.draft_id == draft_id:
                draft.frozen = False
                draft.payload["operator_prompt"] = prompt
                draft.warnings = [*draft.warnings, f"Reevaluated with operator prompt: {prompt}"]
                draft.confidence = min(1.0, draft.confidence + 0.05)
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
                case = self.repository.create_case(draft.payload.get("raw_input", draft.title), "GRAPH1_CONFIRM", actor)
                extraction = self.extractor.extract(draft.payload.get("raw_input", draft.title))
                case = self.repository.save_extraction(case.case_id, extraction, CaseStatus.EXTRACTED)
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

    def _draft_from_payload(self, payload: GraphRunRequest, markdown: str) -> RecordDraft:
        if payload.target == "teams":
            return RecordDraft(
                draft_id=f"draft-{uuid.uuid4().hex[:10]}",
                draft_type=DraftRecordType.TEAM,
                title="Team capability draft",
                payload={"raw_input": markdown, "operator_prompt": payload.operator_prompt},
                confidence=0.68,
            )
        if payload.target == "resources":
            return RecordDraft(
                draft_id=f"draft-{uuid.uuid4().hex[:10]}",
                draft_type=DraftRecordType.RESOURCE,
                title="Resource inventory draft",
                payload={"raw_input": markdown, "operator_prompt": payload.operator_prompt},
                confidence=0.68,
            )
        extraction = self.extractor.extract(markdown)
        return RecordDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:10]}",
            draft_type=DraftRecordType.INCIDENT,
            title=f"{extraction.category} - {extraction.location_text or 'Location pending'}",
            payload={
                "raw_input": markdown,
                "extracted": extraction.model_dump(mode="json"),
                "location_confidence": "UNKNOWN" if extraction.data_quality.missing_location else "APPROXIMATE",
                "operator_prompt": payload.operator_prompt,
            },
            confidence=extraction.confidence,
            warnings=extraction.data_quality.needs_followup_questions,
        )

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
