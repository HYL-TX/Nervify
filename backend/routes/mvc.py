# backend/routes/mvc.py
#
# MVC (Maximum Voluntary Contraction) capture: start a hold, then analyze the
# captured window on finish. Three accepted attempts set the session baseline.

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import config, dsp, session, state

router = APIRouter()


@router.post("/mvc/start")
def start_mvc_capture() -> dict[str, Any]:
    current = session.ensure_session()
    with state.lock:
        session.ensure_prepared(current)
        if len(current.mvc_attempts) >= config.MVC_ATTEMPTS_REQUIRED:
            raise HTTPException(status_code=400, detail="MVC attempts are complete.")
        if (
            current.next_mvc_allowed_at is not None
            and time.time() < current.next_mvc_allowed_at
        ):
            remaining = current.next_mvc_allowed_at - time.time()
            raise HTTPException(
                status_code=400,
                detail=f"Rest {remaining:.1f} more seconds before the next MVC.",
            )
        current.phase = "recording_mvc"
        current.capture_started_at = time.time()
        return session.serialize_session(current)


@router.post("/mvc/finish")
def finish_mvc_capture() -> dict[str, Any]:
    current = session.ensure_session()
    with state.lock:
        if current.phase != "recording_mvc" or current.capture_started_at is None:
            raise HTTPException(status_code=400, detail="No MVC capture is running.")

        # Clamp the analyzed window to MVC_MAX_SECONDS so a long hold (or a late
        # finish) only ever uses the first 10 s of the contraction.
        ended_at = min(time.time(), current.capture_started_at + config.MVC_MAX_SECONDS)
        captured = session.samples_since(current.capture_started_at, ended_at)
        if not captured:
            raise HTTPException(status_code=400, detail="No samples captured for MVC.")

        processed = dsp.process_signal_window(captured)
        if processed["duration_seconds"] < config.CONTRACTION_SECONDS:
            raise HTTPException(
                status_code=400,
                detail="MVC capture must include at least 3 seconds of samples.",
            )

        # Store the MEAN force/EMG over the hold (not the peak), so the MVC
        # baseline uses the same statistic as the trial: %MVC = mean(trial) /
        # mean(MVC). The best-of-3 max across attempts is still applied later in
        # complete_mvc_if_ready_locked.
        attempt = state.MvcAttempt(
            attempt=len(current.mvc_attempts) + 1,
            started_at=processed["started_at"],
            ended_at=processed["ended_at"],
            duration_seconds=processed["duration_seconds"],
            mvc_force=processed["force_n"],
            mvc_emg=processed["total_emg_rms"],
            sample_count=processed["sample_count"],
            emg_clipped=processed["emg_clipped"],
            emg_peak_raw=processed["emg_peak_raw"],
        )
        current.mvc_attempts.append(attempt)
        current.capture_started_at = None
        if len(current.mvc_attempts) < config.MVC_ATTEMPTS_REQUIRED:
            current.phase = "mvc_rest"
            current.next_mvc_allowed_at = time.time() + config.MVC_REST_SECONDS

        session.complete_mvc_if_ready_locked(current)

        return session.serialize_session(current)
