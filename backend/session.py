# backend/session.py
#
# Session/trial domain logic: ingesting samples, the phase guards, the live
# trial monitor that auto-accepts a stable contraction, and serialization of a
# SessionState for the API. Functions ending in `_locked` assume the caller
# already holds state.lock.

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from . import config, dsp, nme, state, storage


def samples_since(started_at: float, ended_at: Optional[float] = None) -> list[state.Sample]:
    stop = ended_at if ended_at is not None else time.time()
    with state.lock:
        return [
            sample
            for sample in state.sample_buffer
            if started_at <= sample.timestamp <= stop
        ]


def add_sample(
    force: float, emg: float, raw: Optional[dict[str, Any]] = None
) -> state.Sample:
    # EMG is read off the device ADC, so it physically cannot exceed the
    # converter ceiling (0..EMG_ADC_MAX). Clamp out-of-range readings into that
    # range instead of trusting them: an impossibly large EMG (a mis-scaled or
    # spoofed sample) would otherwise inflate MVC EMG and silently produce a
    # bogus NME. Clamping to the ceiling also routes the value through the
    # existing saturation guard, which flags the capture as clipped. The raw
    # payload is preserved unchanged for diagnostics.
    emg_value = float(emg)
    clamped_emg = min(max(emg_value, 0.0), config.EMG_ADC_MAX)
    sample = state.Sample(
        timestamp=time.time(),
        force=float(force),
        emg=clamped_emg,
        raw=raw or {"force": force, "emg": emg},
    )

    with state.lock:
        if clamped_emg != emg_value:
            state.serial_status["emg_out_of_range"] += 1
        state.sample_buffer.append(sample)
        # Feed the rolling EMG window whose low percentile is the resting floor
        # subtracted before RMS (keeps NME comparable across sessions).
        state.emg_recent.append(sample.emg)
        state.latest_data.update(
            {
                "force": sample.force,
                "emg": sample.emg,
                "timestamp": sample.timestamp,
                "received_at": datetime.fromtimestamp(
                    sample.timestamp, timezone.utc
                ).isoformat(),
            }
        )
        update_trial_monitor_locked(sample)

    return sample


def ensure_session() -> state.SessionState:
    with state.lock:
        if state.current_session is None:
            raise HTTPException(status_code=400, detail="Start a session first.")
        return state.current_session


def preparation_complete(session: state.SessionState) -> bool:
    return (
        session.preparation.skin_cleaned
        and session.preparation.electrode_on_apb
        and session.preparation.skin_marked
        and session.preparation.hand_positioned
    )


def ensure_prepared(session: state.SessionState) -> None:
    if not preparation_complete(session):
        raise HTTPException(
            status_code=400,
            detail="Complete session preparation before MVC capture.",
        )


def ensure_mvc_ready(session: state.SessionState) -> None:
    if not session.mvc_force or not session.mvc_emg or not session.target_force:
        raise HTTPException(
            status_code=400,
            detail=f"Record {config.MVC_ATTEMPTS_REQUIRED} MVC attempts before trial.",
        )


def complete_mvc_if_ready_locked(session: state.SessionState) -> None:
    if len(session.mvc_attempts) < config.MVC_ATTEMPTS_REQUIRED:
        return

    session.mvc_force = max(attempt.mvc_force for attempt in session.mvc_attempts)
    session.mvc_emg = max(attempt.mvc_emg for attempt in session.mvc_attempts)
    session.target_force = session.mvc_force * (session.target_percentage / 100)
    session.next_mvc_allowed_at = None
    session.phase = "ready_for_trial"


def trial_status_locked(session: state.SessionState) -> dict[str, Any]:
    latest_force = state.latest_data.get("force")
    range_data = nme.target_range(session.target_force)
    in_range = False
    if isinstance(latest_force, (int, float)) and range_data is not None:
        in_range = range_data["lower"] <= latest_force <= range_data["upper"]

    stable_seconds = 0.0
    if session.phase == "monitoring_trial" and session.stable_started_at is not None:
        stable_seconds = max(0.0, time.time() - session.stable_started_at)

    return {
        "phase": session.phase,
        "target_force": session.target_force,
        "target_range": range_data,
        "latest_force": latest_force,
        "latest_emg": state.latest_data.get("emg"),
        "in_target_range": in_range,
        "stable_seconds": stable_seconds,
        "required_stable_seconds": config.CONTRACTION_SECONDS,
        "trial_completed": session.trial_completed,
        "result": session.result,
    }


def finish_trial_locked(
    session: state.SessionState, started_at: float, ended_at: float
) -> None:
    if session.trial_completed:
        return

    trial_samples = samples_since(started_at, ended_at)
    processed = dsp.process_signal_window(trial_samples)
    result = nme.calculate_nme(session, processed)
    storage.save_session_result(result)
    session.phase = "complete"
    session.trial_completed = True
    session.result = result


def update_trial_monitor_locked(sample: state.Sample) -> None:
    session = state.current_session
    if (
        session is None
        or session.phase != "monitoring_trial"
        or session.target_force is None
        or session.trial_completed
    ):
        return

    lower = session.target_force * (1 - config.TARGET_TOLERANCE)
    upper = session.target_force * (1 + config.TARGET_TOLERANCE)

    if lower <= sample.force <= upper:
        if session.stable_started_at is None:
            session.stable_started_at = sample.timestamp
        stable_duration = sample.timestamp - session.stable_started_at
        if stable_duration >= config.CONTRACTION_SECONDS:
            finish_trial_locked(session, session.stable_started_at, sample.timestamp)
    else:
        session.stable_started_at = None


def serialize_session(session: state.SessionState) -> dict[str, Any]:
    data = asdict(session)
    data["preparation_complete"] = preparation_complete(session)
    data["mvc_attempts_required"] = config.MVC_ATTEMPTS_REQUIRED
    data["contraction_seconds"] = config.CONTRACTION_SECONDS
    data["mvc_max_seconds"] = config.MVC_MAX_SECONDS
    data["target_tolerance"] = config.TARGET_TOLERANCE
    if session.phase == "recording_mvc" and session.capture_started_at is not None:
        data["mvc_elapsed_seconds"] = max(0.0, time.time() - session.capture_started_at)
    if session.target_force is not None:
        data["target_range"] = nme.target_range(session.target_force)
    if session.phase == "monitoring_trial" and session.target_force is not None:
        if session.stable_started_at:
            data["stable_seconds"] = max(0.0, time.time() - session.stable_started_at)
        else:
            data["stable_seconds"] = 0.0
    if session.phase == "mvc_rest" and session.next_mvc_allowed_at is not None:
        data["rest_seconds_remaining"] = max(
            0.0, session.next_mvc_allowed_at - time.time()
        )
    return data
