# backend/dsp.py
#
# Signal processing: filtering, RMS windowing, sample-rate estimation, the
# resting EMG baseline, and the full force/EMG analysis of a captured window.
# These functions are pure transforms of the samples handed to them (the one
# exception, current_emg_baseline, reads the shared rolling EMG window).

import math
from datetime import datetime, timezone
from typing import Any, Optional

from . import config, state


def rms(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated q-quantile (q in [0, 1]) of values."""

    if not values:
        return 0.0
    ordered = sorted(values)
    idx = q * (len(ordered) - 1)
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return ordered[int(idx)]
    return ordered[low] + (ordered[high] - ordered[low]) * (idx - low)


def current_emg_baseline() -> float:
    """Resting EMG floor = low percentile of the recent-sample window.

    Robust to single near-zero outliers and to sustained contractions (the
    window keeps enough rest that a low percentile still lands on the floor).
    """

    if not config.EMG_BASELINE_ENABLED:
        return 0.0
    with state.lock:
        if not state.emg_recent:
            return 0.0
        snapshot = list(state.emg_recent)
    return percentile(snapshot, config.EMG_BASELINE_PERCENTILE)


def estimate_sample_rate(samples: list[state.Sample]) -> float:
    if len(samples) < 2:
        return config.DEFAULT_EMG_SAMPLE_RATE_HZ

    duration = samples[-1].timestamp - samples[0].timestamp
    if duration <= 0:
        return config.DEFAULT_EMG_SAMPLE_RATE_HZ
    return (len(samples) - 1) / duration


def low_pass_values(values: list[float], sample_rate_hz: float, cutoff_hz: float) -> list[float]:
    if not values:
        return []

    if sample_rate_hz <= 0 or cutoff_hz <= 0:
        return values

    dt = 1 / sample_rate_hz
    rc = 1 / (2 * math.pi * cutoff_hz)
    alpha = dt / (rc + dt)

    filtered = [values[0]]
    for value in values[1:]:
        filtered.append(filtered[-1] + alpha * (value - filtered[-1]))
    return filtered


def notch_filter_values(
    values: list[float],
    sample_rate_hz: float,
    notch_hz: float = config.NOTCH_FREQUENCY_HZ,
    quality_factor: float = 30.0,
) -> list[float]:
    if len(values) < 3 or sample_rate_hz <= notch_hz * 2:
        return values

    omega = 2 * math.pi * notch_hz / sample_rate_hz
    alpha = math.sin(omega) / (2 * quality_factor)
    b0 = 1
    b1 = -2 * math.cos(omega)
    b2 = 1
    a0 = 1 + alpha
    a1 = -2 * math.cos(omega)
    a2 = 1 - alpha

    filtered: list[float] = []
    x1 = x2 = y1 = y2 = 0.0
    for value in values:
        y0 = (b0 / a0) * value + (b1 / a0) * x1 + (b2 / a0) * x2
        y0 -= (a1 / a0) * y1 + (a2 / a0) * y2
        filtered.append(y0)
        x2, x1 = x1, value
        y2, y1 = y1, y0
    return filtered


def low_pass_force(
    samples: list[state.Sample], sample_rate_hz: Optional[float] = None
) -> list[float]:
    if not samples:
        return []

    rate = sample_rate_hz if sample_rate_hz is not None else estimate_sample_rate(samples)
    return low_pass_values(
        [sample.force for sample in samples],
        sample_rate_hz=rate,
        cutoff_hz=config.FORCE_LOW_PASS_CUTOFF_HZ,
    )


def process_signal_window(
    samples: list[state.Sample], baseline: Optional[float] = None
) -> dict[str, Any]:
    if not samples:
        raise ValueError("No samples were captured.")

    started_at = samples[0].timestamp
    ended_at = samples[-1].timestamp
    duration = max(0.0, ended_at - started_at)
    sample_rate_hz = estimate_sample_rate(samples)
    force_values = low_pass_force(samples, sample_rate_hz)

    # Saturation guard: measure clipping on the RAW ADC values (before any
    # baseline/notch processing), since clipping is a property of the signal
    # hitting the converter/sensor ceiling.
    raw_emg = [sample.emg for sample in samples]
    emg_peak_raw = max(raw_emg)
    saturated_count = sum(1 for value in raw_emg if value >= config.EMG_SATURATION_LEVEL)
    emg_saturated_fraction = saturated_count / len(raw_emg)
    emg_clipped = emg_saturated_fraction > config.EMG_SATURATION_FRACTION

    # Baseline subtraction: remove the resting floor before RMS so a drifting
    # DC offset doesn't change %MVC EMG between sessions.
    if baseline is not None:
        base = baseline
    elif config.EMG_BASELINE_ENABLED:
        base = current_emg_baseline()
    else:
        base = 0.0
    emg_corrected = [max(0.0, value - base) for value in raw_emg]
    emg_values = notch_filter_values(emg_corrected, sample_rate_hz=sample_rate_hz)

    emg_rms_windows: list[float] = []
    window_start = started_at
    while window_start <= ended_at:
        window_end = window_start + config.EMG_WINDOW_SECONDS
        window_values = [
            emg_values[index]
            for index, sample in enumerate(samples)
            if window_start <= sample.timestamp < window_end
        ]
        if window_values:
            emg_rms_windows.append(rms(window_values))
        window_start = window_end

    total_emg_rms = mean(emg_rms_windows) if emg_rms_windows else rms(emg_values)

    return {
        "started_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
        "ended_at": datetime.fromtimestamp(ended_at, timezone.utc).isoformat(),
        "duration_seconds": duration,
        "sample_count": len(samples),
        "estimated_sample_rate_hz": sample_rate_hz,
        "force_n": mean(force_values),
        "peak_force_n": max(sample.force for sample in samples),
        "total_emg_rms": total_emg_rms,
        "peak_emg_rms": max(emg_rms_windows) if emg_rms_windows else total_emg_rms,
        "emg_rms_windows": emg_rms_windows,
        "emg_peak_raw": emg_peak_raw,
        "emg_baseline": base,
        "emg_saturated_fraction": emg_saturated_fraction,
        "emg_clipped": emg_clipped,
        "processing": {
            "emg_notch_hz": config.NOTCH_FREQUENCY_HZ
            if sample_rate_hz > config.NOTCH_FREQUENCY_HZ * 2
            else None,
            "force_low_pass_hz": config.FORCE_LOW_PASS_CUTOFF_HZ,
            "emg_window_seconds": config.EMG_WINDOW_SECONDS,
            "emg_baseline_subtracted": base,
            "emg_saturation_level": config.EMG_SATURATION_LEVEL,
        },
    }
