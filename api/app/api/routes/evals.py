from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import get_repository
from app.models.domain import EvalRunSummary

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/latest", response_model=EvalRunSummary | None)
def latest_eval():
    return get_repository().latest_eval_run()
