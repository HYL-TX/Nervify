# backend/nme.py
#
# The Neuromuscular Efficiency calculation and its supporting domain math:
# the accepted target-force band and the recovery trend versus prior sessions.

from typing import Any, Optional

from . import config, state, storage
from .utils import iso_now


def target_range(target_force: Optional[float]) -> Optional[dict[str, float]]:
    if target_force is None:
        return None
    return {
        "lower": target_force * (1 - config.TARGET_TOLERANCE),
        "upper": target_force * (1 + config.TARGET_TOLERANCE),
    }


def trend_for(nme: float) -> str:
    patient_id = (
        state.current_session.patient_id if state.current_session else None
    )
    previous = [
        session
        for session in storage.load_sessions()
        if patient_id is None or session.get("patient_id") == patient_id
    ]
    if not previous:
        return "baseline"

    previous_nme = previous[-1].get("nme")
    if not isinstance(previous_nme, (int, float)) or previous_nme == 0:
        return "stable"

    change = (nme - previous_nme) / previous_nme
    if change > 0.05:
        return "up"
    if change < -0.05:
        return "down"
    return "stable"


def calculate_nme(session: state.SessionState, processed: dict[str, Any]) -> dict[str, Any]:
    if not session.mvc_force or not session.mvc_emg:
        raise ValueError("MVC force and EMG must be available.")

    force_n = processed["force_n"]
    total_emg_rms = processed["total_emg_rms"]
    percent_mvc_force = (force_n / session.mvc_force) * 100
    percent_mvc_emg = (total_emg_rms / session.mvc_emg) * 100
    nme = percent_mvc_force / percent_mvc_emg if percent_mvc_emg else 0.0
    trend = trend_for(nme)

    # Saturation guard: a clipped MVC caps MVC EMG and makes the NME untrustworthy.
    clipped_attempts = [a.attempt for a in session.mvc_attempts if a.emg_clipped]
    trial_clipped = bool(processed.get("emg_clipped"))
    emg_clipped = trial_clipped or bool(clipped_attempts)
    warnings: list[str] = []
    if clipped_attempts:
        warnings.append(
            f"EMG saturated during MVC attempt(s) {clipped_attempts} — MVC EMG is "
            "capped, so NME is understated. Lower the MyoWare gain and re-record MVC."
        )
    if trial_clipped:
        warnings.append(
            "EMG saturated during the trial — total EMG RMS is capped. "
            "Lower the MyoWare gain and re-run the trial."
        )

    return {
        "session_id": session.session_id,
        "patient_id": session.patient_id,
        "timestamp": iso_now(),
        "mvc_force": session.mvc_force,
        "mvc_emg": session.mvc_emg,
        "target_percentage": session.target_percentage,
        "target_force": session.target_force,
        "target_range": target_range(session.target_force),
        "force_n": force_n,
        "total_emg_rms": total_emg_rms,
        "percent_mvc_force": percent_mvc_force,
        "percent_mvc_emg": percent_mvc_emg,
        "nme": nme,
        "trend": trend,
        "emg_clipped": emg_clipped,
        "emg_baseline": processed.get("emg_baseline"),
        "warnings": warnings,
        "trial": processed,
    }
