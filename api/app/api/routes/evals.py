from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.dependencies import get_repository
from app.core.security import get_current_org_user
from app.models.domain import EvalRunSummary, UserContext

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/latest", response_model=EvalRunSummary | None)
def latest_eval(actor: UserContext = Depends(get_current_org_user)):
    return get_repository().latest_eval_run()
