# backend/routes/system.py
#
# Device/system endpoints: status, the served UI, the live data feed (poll +
# SSE), raw serial inspection, setup/calibration, and the workflow overview.

import asyncio
import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from .. import config, nme, serial_io, session, state
from ..models import ManualSampleRequest, SetupRequest

router = APIRouter()


@router.get("/ui")
def serve_ui() -> FileResponse:
    index = config.FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=404, detail="UI not found. Expected frontend/index.html."
        )
    return FileResponse(index, media_type="text/html")


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
