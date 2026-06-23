# MyoForce — Neuromuscular Efficiency Measurement

**MyoForce** (by Team **Nervify**) measures thumb-muscle **Neuromuscular
Efficiency (NME)** to track a patient's **recovery after carpal tunnel release**.
It records force and EMG during a controlled contraction from an ESP32, computes
NME, and follows the trend across sessions — shipping with a guided web UI and a
per-patient PDF recovery report.

> *Naming:* **MyoForce** is the product; **Nervify** is the team. The codebase,
> this repository, and config identifiers (e.g. `NERVIFY_SERIAL_PORT`) keep the
> original **Nervify** name — only the patient/clinician-facing UI and report are
> branded MyoForce.

> **NME = %MVC force ÷ %MVC EMG.** Both values are normalized to the session's
> own maximum voluntary contraction (MVC), so a higher NME means more force per
> unit of muscle electrical activity — comparable across sessions and patients.

---

## Quick start

```bash
# 1. install dependencies (once)
pip install -r requirements.txt

# 2. start the server (serves the API and the UI)
uvicorn backend.main:app --reload

# 3. open the UI
#    http://127.0.0.1:8000/ui
```

`requirements.txt` lists the top-level dependencies; `requirements.txt.lock`
pins the exact versions used during development — install from it
(`pip install -r requirements.txt.lock`) if you need a reproducible environment.

API docs (interactive Swagger): <http://127.0.0.1:8000/docs>

**Plug in the ESP32 first** so the serial reader connects on startup. The backend
**auto-detects** the USB-serial port (ESP32 / CP210x / CH340 / FTDI), so no
configuration is normally needed. To force a specific port, set
`NERVIFY_SERIAL_PORT` before launching:

`COM7` and `/dev/cu.usbmodemXXXX` below are **examples** — replace them with your
own port (see how to find it just below).

```bash
# Windows (PowerShell) — replace COM7 with your port (COM3, COM5, …)
$env:NERVIFY_SERIAL_PORT="COM7"; uvicorn backend.main:app --reload

# macOS / Linux — replace with your actual device path
NERVIFY_SERIAL_PORT=/dev/cu.usbmodemXXXX uvicorn backend.main:app --reload
```

Find your port in **Device Manager → "Ports (COM & LPT)"** (Windows), or with
`ls /dev/cu.usbmodem*` (macOS) / `ls /dev/ttyUSB* /dev/ttyACM*` (Linux). If you
hit an "Access is denied" / port-busy error, close any other program holding the
port (Arduino Serial Monitor, another running server instance).

This is a single-process app: the backend serves the frontend itself (`/ui` plus
`/static/*`), so there is **no separate frontend server and no build step**.

---

## Using the UI — measurement workflow

The UI walks you left-to-right through six steps. The sidebar shows a live
force/EMG signal, the device connection state (green = ESP32 streaming,
amber = backend up but no device), and quick actions: **Tare load cell**,
**ℹ About NME** (an explainer with references), and **▶ Run demo** (an
auto-playing session for presentations — see [Demo mode](#demo-mode)).

1. **Device Setup** — set the target contraction level (default **20% MVC**).
   Force arrives from the ESP32 already in Newtons. A **Tare load cell** button
   (in Device Setup and in the sidebar) re-zeros the cell on the device — keep it
   unloaded — if its resting force drifts.
2. **Session** — enter a **Patient ID** and start a session. *Use a consistent
   ID per patient* — reports and the recovery trend group by exact-match
   `patient_id`.
3. **Preparation** — tick off the checklist (clean thenar skin, electrode on the
   APB muscle, mark the skin position, position the hand: palm down, wrist
   neutral, thumb on the post, elbow ~90°).
4. **MVC Calibration** — record **3 maximal contractions**. Each: press *Start*,
   pinch as hard as possible; recording auto-stops at 10 s (min 3 s) or when you
   press *Finish*. A **60-second rest** is enforced between attempts. The highest
   force and EMG across the three attempts set `MVC_Force` and `MVC_EMG`, and the
   target force = 20% × MVC_Force.
5. **20% MVC Trial** — the patient gently pinches to hold the force inside the
   target band (±10%) for **3 continuous seconds**. The gauge shows live force vs.
   the band; the trial auto-completes when the hold is stable. (*Force-finish from
   last 3 s* is available as a manual fallback.)
6. **Result** — shows the computed **NME** (higher = better), plain-language
   **progress** vs. the patient's previous session (**Improving / Declining /
   Stable**, or *First session* for a baseline), and the underlying values. Below
   it, **Session History** lists every saved session — numbered per patient — and
   offers PDF report downloads.

### PDF reports

- On the **Result** panel: *⬇ Download PDF report* for the current patient.
- In **Session History**: one report button per distinct patient in the log.

Each report is a self-contained clinical document: a branded header/footer with
page numbers, a patient-information strip, a key-results card, an
**NME-over-sessions chart**, a per-session table (EMG-clipped sessions flagged in
red), and **Clinical Interpretation**, **Measurement Method**, and
**References** sections (primary reference: Rainoldi et al., 2008). It renders in
the Aptos typeface when available and falls back to Helvetica otherwise. Reports
are filtered by exact `patient_id` (sessions with no ID form the "unassigned"
report).

> ⚠ **EMG clipping.** If the MyoWare envelope saturates the ADC, MVC EMG is
> capped and the resulting NME is understated. The UI and the report flag these
> sessions; lower the MyoWare gain and re-record.

### Demo mode

The **▶ Run demo** button (sidebar) plays a full session automatically — setup,
MVC calibration, the 20% trial, and the result — using realistic synthetic
tip-pinch signals (~0–3 N). So the recovery trend and PDF chart are
meaningful, it first **seeds a short prior history** for patient **DEMO** (three
back-dated sessions with rising NME `0.62 → 0.71 → 0.83` and rising MVC force
`2.4 → 3.0 N`), then runs a live final session that lands around **0.95
("Improving")** — both recovery signals, strength magnitude and NME quality,
visibly improving. It's meant for presentations and works with or without the
ESP32 connected: while the demo runs, the backend ignores the real device so the
synthetic signal isn't disturbed. Re-running **replaces** the previous DEMO
history (so runs don't accumulate); delete those entries from
`data/sessions.json` if you don't want them at all.

---

## Project layout

```
backend/              FastAPI application (Python)
├── main.py           entry point: builds the app, mounts routes + static, starts serial reader
├── config.py         all tunable constants and filesystem paths
├── state.py          session dataclasses + shared mutable state (the lock)
├── models.py         Pydantic request bodies
├── dsp.py            signal processing: filters, RMS, baseline, window analysis
├── nme.py            NME calculation, target band, recovery trend
├── storage.py        load/save the session results log
├── report.py         per-patient PDF report (reportlab)
├── serial_io.py      ESP32 serial parsing + the background reader thread
├── session.py        session/trial domain logic (phase guards, trial monitor)
└── routes/           HTTP endpoints, grouped by area
    ├── system.py     status, UI, live data/stream, setup, workflow
    ├── session.py    session lifecycle, saved results, PDF report
    ├── mvc.py        MVC capture
    └── trial.py      20% MVC monitoring trial
frontend/             single-page UI: index.html + styles.css + app.js
firmware/             ESP32 Arduino sketch (firmware/nervify_esp32/)
data/                 sessions.json result log (created on first save)
docs/                 plan.md (pipeline logic), explanation.md (API testing guide)
tests/                test_serial.py (raw serial sniffer)
```

---

## API reference

| Method & path | Purpose |
|---|---|
| `GET /` | Status: phase, current session, serial connection |
| `GET /ui` | The web UI |
| `GET /data` · `GET /stream` | Latest force/EMG (poll) · live SSE feed (~20 Hz) |
| `POST /data` | Inject a manual `{force, emg}` sample (testing) |
| `GET /serial/raw` | Raw serial lines + parse diagnostics |
| `GET·POST /setup` | Read / set target % of MVC |
| `POST /setup/tare` | Tell the device to re-zero (tare) the load cell |
| `POST /demo/start` · `/demo/stop` | Enter / leave presentation demo mode (serial reader ignores the real device) |
| `POST /demo/seed-history` | Plant a back-dated, rising-NME session history for the demo patient |
| `GET /workflow` | Step-by-step completion overview |
| `POST /session/start` · `/session/prepare` · `/session/reset` | Session lifecycle |
| `POST /mvc/start` · `/mvc/finish` · `/mvc/skip-rest` · `/mvc/restart` | MVC capture (×3); skip the 60 s rest lock; restart calibration |
| `POST /trial/start` · `GET /trial/status` · `POST /trial/finish` | Trial monitoring |
| `GET /session` · `GET /sessions` | Current session · all saved sessions |
| `GET /result/latest` | Most recent saved result |
| `GET /report?patient_id=<id>` | **Per-patient PDF report** (omit id → unassigned) |

The signal pipeline (sample rates, filters, RMS windowing, NME math) is
documented step by step in [`docs/plan.md`](docs/plan.md); an endpoint-by-endpoint
manual test walkthrough is in [`docs/explanation.md`](docs/explanation.md).

---

## ESP32 firmware

The sketch lives in `firmware/nervify_esp32/` (Arduino requires the `.ino` to sit
in a folder of the same name). It should stream one JSON object per line:

```json
{"force":2.95,"emg":189}
```

The backend tolerates minor framing glitches but rejects unparseable lines
(visible via `GET /serial/raw`).

---

## Troubleshooting

**`connected: false` or "no device" in the UI**
1. Close anything else holding the port — Arduino Serial Monitor, the VS Code
   Serial Monitor, `tests/test_serial.py`, or a second server instance. Only one
   process can hold a serial port (an `Access is denied` / `PermissionError` in
   `GET /serial/raw` means the port is busy).
2. The port is auto-detected; if the wrong device is picked, set
   `NERVIFY_SERIAL_PORT` (e.g. `COM7`, or `/dev/cu.usbmodemXXXX`). Check the
   detected port and any error under `serial` in `GET /serial/raw`.
3. Unplug/replug the ESP32, then restart the server.

The UI reports connection by *recent data flow*, not the raw port handle, so a
brief reopen won't flash a disconnect. A few rejected lines at device startup is
normal; a rapidly climbing `lines_rejected` during a trial is not.

**Reports/History are empty** — `data/sessions.json` starts as `[]`; complete a
trial to populate it.

**Port already in use on start** — a server is already running on 8000. Reuse it,
or start on another port: `uvicorn backend.main:app --port 8001`.
