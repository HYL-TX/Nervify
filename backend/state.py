# backend/state.py
#
# Dataclasses describing a measurement session, plus the shared mutable state
# the serial reader thread and the request handlers both touch. Everything here
# is guarded by `lock`; helpers whose names end in `_locked` assume the caller
# already holds it.
#
# IMPORTANT: `current_session` is rebound (not mutated) when a session starts or
# resets. Always read/write it as `state.current_session` -- never
# `from .state import current_session`, which would capture a stale binding.

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from . import config


@dataclass
class Sample:
    timestamp: float
    force: float
    emg: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MvcAttempt:
    attempt: int
    started_at: str
    ended_at: str
    duration_seconds: float
    mvc_force: float
    mvc_emg: float
    sample_count: int
    emg_clipped: bool = False
    emg_peak_raw: Optional[float] = None


@dataclass
class PreparationChecklist:
    skin_cleaned: bool = False
    electrode_on_apb: bool = False
    skin_marked: bool = False
    hand_positioned: bool = False
    notes: Optional[str] = None


@dataclass
class SessionState:
    session_id: str
    patient_id: Optional[str]
    started_at: str
    target_percentage: float = config.TARGET_PERCENTAGE
    preparation: PreparationChecklist = field(default_factory=PreparationChecklist)
    mvc_attempts: list[MvcAttempt] = field(default_factory=list)
    mvc_force: Optional[float] = None
    mvc_emg: Optional[float] = None
    target_force: Optional[float] = None
    phase: str = "preparation"
    capture_started_at: Optional[float] = None
    next_mvc_allowed_at: Optional[float] = None
    stable_started_at: Optional[float] = None
    trial_completed: bool = False
    result: Optional[dict[str, Any]] = None


# ---- Shared mutable state (guard with `lock`) ----
lock = threading.RLock()
sample_buffer: deque[Sample] = deque(maxlen=120_000)
raw_serial_lines: deque[dict[str, Any]] = deque(maxlen=200)
latest_data: dict[str, Any] = {"force": 0.0, "emg": 0.0}
# Rolling window of recent EMG samples; its low percentile is the resting floor
# subtracted before RMS so baseline drift doesn't move NME between sessions.
emg_recent: deque[float] = deque(maxlen=config.EMG_BASELINE_WINDOW_SAMPLES)
current_session: Optional[SessionState] = None
# When True, the serial reader ignores real device samples so the presentation
# demo can drive the pipeline with synthetic samples without interference.
demo_active: bool = False
serial_status: dict[str, Any] = {
    "connected": False,
    "port": config.SERIAL_PORT or "auto",
    "baud_rate": config.BAUD_RATE,
    "last_error": None,
    "last_parse_error": None,
    "last_line": None,
    "samples_received": 0,
    "lines_rejected": 0,
    "emg_out_of_range": 0,
    "read_errors": 0,
    "last_connected_at": None,
    "last_sample_at": None,
    "last_command": None,
    "last_command_at": None,
}
runtime_setup = {
    "target_percentage": config.TARGET_PERCENTAGE,
}
