# backend/routes/session.py
#
# Session lifecycle (start / prepare / reset / inspect) and the saved-result log.

import re
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .. import report, session, state, storage
from ..models import PreparationRequest, StartSessionRequest
from ..utils import iso_now

router = APIRouter()


@router.post("/session/start")
def start_session(request: StartSessionRequest) -> dict[str, Any]:
    with state.lock:
        state.current_session = state.SessionState(
            session_id=str(uuid4()),
            patient_id=request.patient_id,
            started_at=iso_now(),
            target_percentage=state.runtime_setup["target_percentage"],
        )
        return session.serialize_session(state.current_session)


@router.post("/session/prepare")
def update_preparation(request: PreparationRequest) -> dict[str, Any]:
    current = session.ensure_session()
    with state.lock:
        current.preparation = state.PreparationChecklist(**request.dict())
        if session.preparation_complete(current) and current.phase == "preparation":
            current.phase = "ready_for_mvc"
        elif (
            not session.preparation_complete(current)
            and current.phase == "ready_for_mvc"
        ):
            current.phase = "preparation"
        return session.serialize_session(current)


@router.post("/session/reset")
def reset_session() -> dict[str, Any]:
    with state.lock:
        state.current_session = None
        return {"phase": "idle"}


@router.get("/session")
def get_current_session() -> dict[str, Any]:
    current = session.ensure_session()
    with state.lock:
        return session.serialize_session(current)


@router.get("/sessions")
def get_saved_sessions() -> list[dict[str, Any]]:
    return storage.load_sessions()


@router.get("/result/latest")
def get_latest_result() -> dict[str, Any]:
    sessions = storage.load_sessions()
    if not sessions:
        raise HTTPException(status_code=404, detail="No saved session results found.")
    return sessions[-1]


@router.get("/report")
def patient_report(patient_id: Optional[str] = None) -> Response:
    """PDF recovery report for one patient (omit patient_id for unassigned)."""

    pdf = report.build_patient_report(patient_id)
    if pdf is None:
        label = patient_id or "unassigned"
        raise HTTPException(
            status_code=404, detail=f"No saved sessions for patient '{label}'."
        )
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", patient_id or "unassigned").strip("-")
    filename = f"nervify_report_{slug or 'unassigned'}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
