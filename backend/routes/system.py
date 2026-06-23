# backend/routes/system.py
#
# Device/system endpoints: status, the served UI, the live data feed (poll +
# SSE), raw serial inspection, setup/calibration, and the workflow overview.

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from .. import config, nme, serial_io, session, state, storage
from ..models import DemoSeedRequest, ManualSampleRequest, SetupRequest

router = APIRouter()


@router.get("/ui")
def serve_ui() -> FileResponse:
    index = config.FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=404, detail="UI not found. Expected frontend/index.html."
        )
    # Always revalidate the HTML so updated CSS/JS (with bumped ?v=) is picked
    # up on a normal reload instead of being masked by a stale cached page.
    return FileResponse(
        index,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/")
def root() -> dict[str, Any]:
    with state.lock:
        phase = state.current_session.phase if state.current_session else "idle"
        session_summary = (
            session.serialize_session(state.current_session)
            if state.current_session
            else None
        )
        serial_snapshot = dict(state.serial_status)
        # Report connection by recent data flow, not the raw port handle, so a
        # momentary reopen doesn't surface as a disconnect in the UI.
        serial_snapshot["connected"] = serial_io.serial_is_live()
        return {
            "name": "Nervify NME Measurement API",
            "phase": phase,
            "setup": dict(state.runtime_setup),
            "session": session_summary,
            "serial": serial_snapshot,
        }


@router.get("/data")
def get_data() -> dict[str, Any]:
    with state.lock:
        return dict(state.latest_data)


@router.get("/stream")
async def stream_data() -> StreamingResponse:
    """Server-Sent Events: push the latest force/EMG + connection state at ~20 Hz.

    The GUI uses this instead of polling /data so the live signal has no
    perceptible lag, and so it can tell "device is streaming" from
    "backend up but no samples" by watching samples_received move.
    """

    async def event_gen():
        while True:
            with state.lock:
                snapshot = {
                    "force": state.latest_data.get("force"),
                    "emg": state.latest_data.get("emg"),
                    "timestamp": state.latest_data.get("timestamp"),
                    "connected": serial_io.serial_is_live(),
                    "samples_received": state.serial_status["samples_received"],
                    "lines_rejected": state.serial_status["lines_rejected"],
                }
            yield f"data: {json.dumps(snapshot)}\n\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/serial/raw")
def get_raw_serial_lines() -> dict[str, Any]:
    with state.lock:
        return {
            "serial": dict(state.serial_status),
            "lines": list(state.raw_serial_lines),
        }


@router.post("/data")
def add_manual_sample(sample: ManualSampleRequest) -> dict[str, Any]:
    created = session.add_sample(sample.force, sample.emg)
    return asdict(created)


@router.post("/setup")
def update_setup(request: SetupRequest) -> dict[str, Any]:
    state.runtime_setup["target_percentage"] = request.target_percentage
    return dict(state.runtime_setup)


@router.get("/setup")
def get_setup() -> dict[str, Any]:
    return {
        **state.runtime_setup,
        "target_tolerance": config.TARGET_TOLERANCE,
        "mvc_attempts_required": config.MVC_ATTEMPTS_REQUIRED,
        "mvc_rest_seconds": config.MVC_REST_SECONDS,
        "contraction_seconds": config.CONTRACTION_SECONDS,
        "mvc_max_seconds": config.MVC_MAX_SECONDS,
        "emg_window_seconds": config.EMG_WINDOW_SECONDS,
        "force_low_pass_hz": config.FORCE_LOW_PASS_CUTOFF_HZ,
        "emg_notch_hz": config.NOTCH_FREQUENCY_HZ,
    }


@router.post("/setup/tare")
def tare_load_cell() -> dict[str, Any]:
    """Tell the device to re-zero the load cell (HX711 tare).

    The cell must be UNLOADED when this runs, or the new zero baseline -- and
    every force reading after it -- will be wrong. We require a live stream so
    the command can't be silently queued against an absent device.
    """

    if not serial_io.serial_is_live():
        raise HTTPException(
            status_code=409,
            detail="Device is not streaming; connect it before taring.",
        )

    serial_io.queue_command("TARE")
    return {
        "status": "ok",
        "command": "TARE",
        "note": "Re-zeroing the load cell. Keep it unloaded.",
    }


@router.post("/demo/start")
def demo_start() -> dict[str, Any]:
    """Enter demo mode: the serial reader ignores real device samples so the
    presentation demo can drive the pipeline with synthetic samples."""
    with state.lock:
        state.demo_active = True
    return {"status": "ok", "demo_active": True}


@router.post("/demo/stop")
def demo_stop() -> dict[str, Any]:
    """Leave demo mode and resume normal device sample ingestion."""
    with state.lock:
        state.demo_active = False
    return {"status": "ok", "demo_active": False}


@router.post("/demo/seed-history")
def demo_seed_history(req: DemoSeedRequest) -> dict[str, Any]:
    """Plant a series of completed sessions with rising NME for the demo patient
    so the recovery trend and the PDF report chart have history to display. The
    presentation demo calls this before running its live final session.

    Each seeded session holds force at the 20% target (so %MVC force ≈ 20) and
    backs out %MVC EMG from the requested NME; MVC force rises across sessions so
    the demo shows both recovery signals — strength magnitude and NME quality —
    improving together. Sessions are back-dated `days_apart` apart."""
    if req.replace:
        storage.delete_patient_sessions(req.patient_id)

    n = len(req.nme_series)
    forces = req.mvc_force_series or [round(2.4 + 0.3 * i, 2) for i in range(n)]
    now = datetime.now(timezone.utc)

    seeded: list[dict[str, Any]] = []
    prev_nme: float | None = None
    for i, nme_value in enumerate(req.nme_series):
        mvc_force = forces[i] if i < len(forces) else forces[-1]
        mvc_emg = req.mvc_emg
        percent_mvc_force = 20.0
        percent_mvc_emg = percent_mvc_force / nme_value
        target_force = mvc_force * 0.20
        total_emg_rms = mvc_emg * percent_mvc_emg / 100.0
        days_ago = (n - i) * req.days_apart      # oldest first; newest ≈ days_apart ago
        timestamp = (now - timedelta(days=days_ago)).isoformat()

        if prev_nme is None:
            trend = "baseline"
        elif (nme_value - prev_nme) / prev_nme > 0.05:
            trend = "up"
        elif (nme_value - prev_nme) / prev_nme < -0.05:
            trend = "down"
        else:
            trend = "stable"
        prev_nme = nme_value

        result = {
            "session_id": str(uuid.uuid4()),
            "patient_id": req.patient_id,
            "timestamp": timestamp,
            "mvc_force": mvc_force,
            "mvc_emg": mvc_emg,
            "target_percentage": percent_mvc_force,
            "target_force": target_force,
            "target_range": nme.target_range(target_force),
            "force_n": target_force,
            "total_emg_rms": total_emg_rms,
            "percent_mvc_force": percent_mvc_force,
            "percent_mvc_emg": percent_mvc_emg,
            "nme": round(nme_value, 3),
            "trend": trend,
            "emg_clipped": False,
            "emg_baseline": 0.0,
            "warnings": [],
            "trial": {},
        }
        storage.save_session_result(result)
        seeded.append({"nme": result["nme"], "timestamp": timestamp, "trend": trend})

    return {"status": "ok", "patient_id": req.patient_id, "seeded": seeded}


@router.get("/workflow")
def get_workflow() -> dict[str, Any]:
    with state.lock:
        current = state.current_session
        return {
            "steps": [
                {
                    "step": 0,
                    "name": "One-time device setup",
                    "done": state.runtime_setup["target_percentage"] is not None,
                    "target_percentage": state.runtime_setup["target_percentage"],
                },
                {
                    "step": 1,
                    "name": "Session preparation",
                    "done": session.preparation_complete(current) if current else False,
                },
                {
                    "step": 2,
                    "name": "MVC calibration",
                    "done": bool(current and current.mvc_force and current.mvc_emg),
                    "attempts_required": config.MVC_ATTEMPTS_REQUIRED,
                    "attempts_completed": len(current.mvc_attempts) if current else 0,
                },
                {
                    "step": 3,
                    "name": "Monitoring contraction",
                    "done": bool(current and current.trial_completed),
                    "target_tolerance": config.TARGET_TOLERANCE,
                    "contraction_seconds": config.CONTRACTION_SECONDS,
                    "target_force": current.target_force if current else None,
                    "target_range": nme.target_range(current.target_force)
                    if current
                    else None,
                },
                {
                    "step": 4,
                    "name": "Signal processing",
                    "done": bool(current and current.result),
                },
                {
                    "step": 5,
                    "name": "NME calculation",
                    "done": bool(current and current.result),
                },
                {
                    "step": 6,
                    "name": "Store and display results",
                    "done": bool(current and current.result),
                },
            ],
            "current_session": session.serialize_session(current) if current else None,
        }
