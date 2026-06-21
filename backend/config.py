# backend/config.py
#
# All tunable constants and filesystem paths for the backend. No other module
# defines configuration -- everything imports from here, so there is a single
# place to look when changing a threshold, a port, or a directory layout.

import os
from pathlib import Path

# Paths are resolved relative to the project root (the parent of this package)
# so the backend keeps working no matter what directory uvicorn is launched in.
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
SESSION_LOG_PATH = DATA_DIR / "sessions.json"

# Override without editing source: NERVIFY_SERIAL_PORT=/dev/cu.usbmodemXXXX uvicorn app:app
SERIAL_PORT = os.environ.get("NERVIFY_SERIAL_PORT", "/dev/cu.usbmodem14101")
BAUD_RATE = 115200
TARGET_PERCENTAGE = 20.0
TARGET_TOLERANCE = 0.10
MVC_ATTEMPTS_REQUIRED = 3
CONTRACTION_SECONDS = 3.0
# Upper bound on a single MVC hold. The GUI auto-finishes at this point; the
# backend also clamps the analyzed window to it, so a hold that runs long (or a
# late /mvc/finish) never analyzes more than this many seconds.
MVC_MAX_SECONDS = 10.0
MVC_REST_SECONDS = 60.0
EMG_WINDOW_SECONDS = 0.5
DEFAULT_EMG_SAMPLE_RATE_HZ = 1000.0
FORCE_LOW_PASS_CUTOFF_HZ = 10.0
NOTCH_FREQUENCY_HZ = 60.0
# EMG saturation guard. The ESP32 ADC is 12-bit (0-4095) by default; the MyoWare
# envelope rails a little below that. Any raw sample at/above EMG_SATURATION_LEVEL
# counts as "railed", and if more than EMG_SATURATION_FRACTION of a capture is
# railed the EMG is flagged as clipped -- a clipped MVC silently produces a bad
# NME (capped MVC EMG -> inflated %MVC EMG -> deflated NME), so we surface it.
EMG_ADC_MAX = float(os.environ.get("NERVIFY_EMG_ADC_MAX", "4095"))
EMG_SATURATION_LEVEL = 0.90 * EMG_ADC_MAX
EMG_SATURATION_FRACTION = 0.05
# Resting EMG baseline subtraction. The MyoWare envelope sits on a DC floor that
# drifts with skin/electrode condition between sessions; subtracting the resting
# floor before RMS keeps %MVC EMG (and thus NME) comparable session to session.
# The floor is the low percentile of a rolling window of recent samples: a low
# percentile is the resting level (the signal spends most of its time at rest),
# is immune to a single stray near-zero reading (which an absolute-minimum
# tracker latches onto), and ignores contractions as long as the window holds
# some rest -- which it always does given the 60 s MVC rests and pre-trial idle.
EMG_BASELINE_ENABLED = os.environ.get("NERVIFY_EMG_BASELINE", "1") != "0"
EMG_BASELINE_PERCENTILE = 0.20
EMG_BASELINE_WINDOW_SAMPLES = 15000  # ~30 s at the device's ~500 Hz stream
# The device only counts as "connected" if a sample arrived this recently. The
# port can momentarily glitch (a stray read exception, a reopen) without the
# ESP32 actually being gone; tying connection state to recent data flow instead
# of the raw open/closed handle keeps the UI from flapping on sub-second blips.
SAMPLE_FRESHNESS_SECONDS = 2.0
