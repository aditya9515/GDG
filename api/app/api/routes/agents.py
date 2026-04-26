from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_agent_graph_service, get_repository
from app.core.security import get_current_org_user
from app.models.domain import (
    BatchCaseEditRequest,
    BatchConfirmCaseRequest,
    BatchPlanningRequest,
    BatchReplanRequest,
    GraphEditRequest,
    GraphRemoveRequest,
    GraphResumeRequest,
    GraphRunRequest,
    GraphRunResponse,
    DeleteResponse,
    UserContext,
)

router = APIRouter(prefix="/agent", tags=["agent-graphs"])


@router.post("/graph1/run", response_model=GraphRunResponse)
def run_graph1(payload: GraphRunRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().run_graph1(payload, actor))


@router.post("/graph1/run-file", response_model=GraphRunResponse)
async def run_graph1_file(
    target: str = Form("incidents"),
    source_kind: str = Form("CSV"),
    operator_prompt: str | None = Form(None),
    file: UploadFile = File(...),
    actor: UserContext = Depends(get_current_org_user),
):
    content = await file.read()
    return GraphRunResponse(
        run=get_agent_graph_service().run_graph1_file(
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            source_kind=source_kind,
            target=target,
            operator_prompt=operator_prompt,
            actor=actor,
        )
    )


@router.post("/graph1/run/{run_id}/edit", response_model=GraphRunResponse)
def edit_graph1(run_id: str, payload: GraphEditRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().edit_graph_run(run_id, payload.prompt or "", actor, payload.draft_id, payload.field_updates))


@router.post("/graph1/run/{run_id}/remove", response_model=GraphRunResponse)
def remove_graph1(run_id: str, payload: GraphRemoveRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().remove_draft(run_id, payload.draft_id, payload.reason, actor))


@router.post("/graph1/run/{run_id}/confirm", response_model=GraphRunResponse)
def confirm_graph1(run_id: str, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().confirm_graph1(run_id, actor))


@router.post("/graph2/run", response_model=GraphRunResponse)
def run_graph2(payload: GraphRunRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().run_graph2(payload, actor))


@router.post("/graph2/batch-run", response_model=GraphRunResponse)
def run_graph2_batch(payload: BatchPlanningRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().run_graph2_batch(payload, actor))


@router.post("/graph2/run/{run_id}/resume", response_model=GraphRunResponse)
def resume_graph2(run_id: str, payload: GraphResumeRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().resume_graph2(run_id, payload.answers, actor))


@router.post("/graph2/run/{run_id}/edit", response_model=GraphRunResponse)
def edit_graph2(run_id: str, payload: GraphEditRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().edit_graph_run(run_id, payload.prompt or "", actor, payload.draft_id, payload.field_updates))


@router.post("/graph2/run/{run_id}/confirm", response_model=GraphRunResponse)
def confirm_graph2(run_id: str, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().confirm_graph2(run_id, actor))


@router.post("/graph2/run/{run_id}/edit-case", response_model=GraphRunResponse)
def edit_graph2_batch_case(run_id: str, payload: BatchCaseEditRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(
        run=get_agent_graph_service().edit_batch_case_plan(
            run_id,
            payload.case_id,
            actor,
            payload.prompt,
            payload.field_updates,
        )
    )


@router.post("/graph2/run/{run_id}/replan-global", response_model=GraphRunResponse)
def replan_graph2_batch(run_id: str, payload: BatchReplanRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().replan_graph2_batch(run_id, payload, actor))


@router.post("/graph2/run/{run_id}/confirm-batch", response_model=GraphRunResponse)
def confirm_graph2_batch(run_id: str, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().confirm_graph2_batch(run_id, actor))


@router.post("/graph2/run/{run_id}/confirm-case", response_model=GraphRunResponse)
def confirm_graph2_batch_case(run_id: str, payload: BatchConfirmCaseRequest, actor: UserContext = Depends(get_current_org_user)):
    return GraphRunResponse(run=get_agent_graph_service().confirm_graph2_batch_case(run_id, payload.case_id, actor))


@router.post("/graph3/run", response_model=GraphRunResponse)
def run_graph3(payload: GraphRunRequest, actor: UserContext = Depends(get_current_org_user)):
    # V1 graph3 starts the intake graph; dispatch graph is launched after operator confirmation.
    return GraphRunResponse(run=get_agent_graph_service().run_graph1(payload, actor))


@router.get("/runs/{run_id}", response_model=GraphRunResponse)
def get_run(run_id: str, actor: UserContext = Depends(get_current_org_user)):
    run = get_repository().get_graph_run(run_id)
    if run.org_id != actor.active_org_id:
        raise HTTPException(status_code=403, detail="Graph run belongs to another organization.")
    return GraphRunResponse(run=run)


@router.delete("/runs/{run_id}", response_model=DeleteResponse)
def delete_run(run_id: str, actor: UserContext = Depends(get_current_org_user)):
    try:
        get_repository().delete_graph_run(run_id, actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Graph run not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return DeleteResponse(deleted_id=run_id, deleted_type="graph_run", request_id=f"req-{uuid.uuid4().hex[:12]}")


@router.get("/runs/{run_id}/export.csv")
def export_run(run_id: str, actor: UserContext = Depends(get_current_org_user)):
    run = get_repository().get_graph_run(run_id)
    if run.org_id != actor.active_org_id:
        raise HTTPException(status_code=403, detail="Graph run belongs to another organization.")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    batch_draft = next((draft for draft in run.drafts if isinstance(draft.payload.get("batch_plan"), dict)), None)
    if batch_draft is not None:
        writer.writerow(
            [
                "run_id",
                "case_id",
                "rank",
                "status",
                "priority_score",
                "planning_priority_score",
                "team_id",
                "eta_minutes",
                "match_score",
                "reasons",
                "unmet_requirements",
            ]
        )
        for item in batch_draft.payload["batch_plan"].get("planned_cases", []):
            selected = item.get("selected_recommendation") or {}
            writer.writerow(
                [
                    run.run_id,
                    item.get("case_id"),
                    item.get("priority_rank"),
                    item.get("assignment_status"),
                    item.get("priority_score"),
                    item.get("planning_priority_score"),
                    selected.get("team_id"),
                    selected.get("eta_minutes"),
                    selected.get("match_score"),
                    " | ".join(item.get("reasons") or []),
                    " | ".join(item.get("unmet_requirements") or []),
                ]
            )
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{run_id}-batch-dispatch.csv"'},
        )

    writer.writerow(["run_id", "graph_name", "status", "draft_id", "draft_type", "title", "confidence", "committed_records"])
    for draft in run.drafts:
        writer.writerow(
            [
                run.run_id,
                run.graph_name,
                run.status,
                draft.draft_id,
                draft.draft_type,
                draft.title,
                draft.confidence,
                "|".join(run.committed_record_ids),
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={run_id}.csv"},
    )
