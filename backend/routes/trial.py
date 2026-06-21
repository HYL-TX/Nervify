# backend/routes/trial.py
#
# The 20% MVC monitoring trial: start monitoring, poll live status, or
# force-finish from the most recent stable samples.

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import config, session, state

router = APIRouter()


@router.post("/trial/start")
def start_trial_monitoring() -> dict[str, Any]:
    current = session.ensure_session()
    with state.lock:
        session.ensure_mvc_ready(current)
        current.phase = "monitoring_trial"
        current.stable_started_at = None
        current.trial_completed = False
        current.result = None
        return session.serialize_session(current)


@router.get("/trial/status")
def get_trial_status() -> dict[str, Any]:
    current = session.ensure_session()
    with state.lock:
        return session.trial_status_locked(current)


@router.post("/trial/finish")
def finish_trial_from_recent_samples() -> dict[str, Any]:
    current = session.ensure_session()
    with state.lock:
        session.ensure_mvc_ready(current)
        ended_at = time.time()
        started_at = ended_at - config.CONTRACTION_SECONDS
        captured = session.samples_since(started_at, ended_at)
        if not captured:
            raise HTTPException(status_code=400, detail="No recent trial samples found.")

        target_force = current.target_force or 0
        lower = target_force * (1 - config.TARGET_TOLERANCE)
        upper = target_force * (1 + config.TARGET_TOLERANCE)
        out_of_range = [
            sample.force
            for sample in captured
            if sample.force < lower or sample.force > upper
        ]
        if out_of_range:
            raise HTTPException(
                status_code=400,
                detail="Recent samples were not stable within the target force range.",
            )

        session.finish_trial_locked(current, captured[0].timestamp, captured[-1].timestamp)
        return current.result or {}
