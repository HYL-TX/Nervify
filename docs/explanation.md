# Backend Testing Guide

This guide explains how to test the Nervify NME Measurement API from start to
finish.

## 1. Start the Backend

From the project folder, run:

```bash
uvicorn backend.main:app --reload
```

Then open the API docs:

```text
http://127.0.0.1:8000/docs
```

The docs page lets you click an endpoint, select **Try it out**, enter JSON,
and press **Execute**.

## 2. Check Serial Connection

Open:

```text
GET /
```

You should see something like:

```json
{
  "name": "Nervify NME Measurement API",
  "phase": "idle",
  "serial": {
    "connected": true,
    "port": "/dev/cu.usbmodem14101",
    "samples_received": 10,
    "last_line": "{\"force\":2.95,\"emg\":189}"
  }
}
```

Important fields:

- `connected`: should usually be `true`.
- `samples_received`: should increase while the ESP32 sends data.
- `last_line`: should look like `{"force":2.95,"emg":189}`.
- `lines_rejected`: should not increase rapidly during normal use.

If `connected` is `false`, close Arduino Serial Monitor, stop `test_serial.py`,
and make sure no other app is using the same serial port.

## 3. Configure Setup

Call:

```text
POST /setup
```

Body:

```json
{
  "target_percentage": 20,
  "load_cell_calibration_factor": null
}
```

This sets the trial target to 20% of MVC.

If the load cell's resting force drifts away from zero, re-zero it with:

```text
POST /setup/tare
```

This sends a `TARE` command to the ESP32, which calls `scale.tare()` to reset
the zero baseline. Keep the load cell unloaded while taring, and note the
device must be streaming (the call returns `409` otherwise).

## 4. Start a Session

Call:

```text
POST /session/start
```

Body:

```json
{
  "patient_id": "patient-001"
}
```

The response should show:

```json
"phase": "preparation"
```

## 5. Mark Preparation Complete

Call:

```text
POST /session/prepare
```

Body:

```json
{
  "skin_cleaned": true,
  "electrode_on_apb": true,
  "skin_marked": true,
  "hand_positioned": true,
  "notes": "ready"
}
```

The response should show:

```json
"phase": "ready_for_mvc"
```

This represents the research preparation step:

- clean the thenar skin area
- place the EMG electrode on the APB muscle
- mark the skin position
- position the hand correctly

## 6. Record MVC Attempts

MVC means Maximum Voluntary Contraction. The patient should pinch as hard as
possible for at least 3 seconds.

Call:

```text
POST /mvc/start
```

Then wait while the patient pinches hard for 3 seconds.

After that, call:

```text
POST /mvc/finish
```

Repeat this process until 3 MVC attempts are complete:

```text
MVC attempt 1: /mvc/start -> pinch hard 3 seconds -> /mvc/finish
MVC attempt 2: /mvc/start -> pinch hard 3 seconds -> /mvc/finish
MVC attempt 3: /mvc/start -> pinch hard 3 seconds -> /mvc/finish
```

After attempts 1 and 2, the backend may require a 60 second rest period. If you
call `/mvc/start` too early, it will return a message telling you how many
seconds remain.

After the third MVC attempt, the response should show:

```json
"phase": "ready_for_trial"
```

It should also include:

- `mvc_force`
- `mvc_emg`
- `target_force`
- `target_range`

The target force is calculated as:

```text
target_force = 20% * mvc_force
```

## 7. Start the 20% MVC Trial

Call:

```text
POST /trial/start
```

The patient should pinch gently and try to keep the force inside the target
range.

Watch the trial status with:

```text
GET /trial/status
```

Important fields:

- `target_force`: the force the patient should aim for
- `target_range.lower`: minimum accepted force
- `target_range.upper`: maximum accepted force
- `latest_force`: current force from the ESP32
- `in_target_range`: whether the current force is accepted
- `stable_seconds`: how long the force has stayed in range

The backend accepts the trial when force stays within the target range for 3
seconds.

The acceptance rule is:

```text
force >= target_force * 0.90
force <= target_force * 1.10
stable for 3 seconds
```

If the force leaves the range, the stable timer resets.

## 8. Read the NME Result

After the trial completes, call:

```text
GET /result/latest
```

The response includes:

- `mvc_force`
- `mvc_emg`
- `force_n`
- `total_emg_rms`
- `percent_mvc_force`
- `percent_mvc_emg`
- `nme`
- `trend`

The NME calculation is:

```text
percent_mvc_force = (force_n / mvc_force) * 100
percent_mvc_emg = (total_emg_rms / mvc_emg) * 100
nme = percent_mvc_force / percent_mvc_emg
```

Saved results are stored in:

```text
data/sessions.json
```

You can view all saved sessions with:

```text
GET /sessions
```

## 9. Useful Debug Endpoints

Check the current workflow:

```text
GET /workflow
```

Check latest force and EMG:

```text
GET /data
```

Check raw serial lines:

```text
GET /serial/raw
```

Reset the current in-memory session:

```text
POST /session/reset
```

This does not delete saved results from `data/sessions.json`.

## 10. Common Serial Problems

If `GET /` shows:

```json
"connected": false
```

or:

```text
device reports readiness to read but returned no data
```

check these things:

1. Close Arduino Serial Monitor.
2. Stop `test_serial.py` if it is running.
3. Make sure only the backend is using `/dev/cu.usbmodem14101`.
4. Unplug and reconnect the ESP32 if needed.
5. Restart the backend.

The ESP32 should ideally send one JSON object per line:

```json
{"force":2.95,"emg":189}
```

Malformed lines may be rejected. A small number of rejected lines during ESP32
startup is okay, but rejected lines should not increase quickly during a normal
trial.

## Short Test Flow

```text
GET /
POST /setup
POST /session/start
POST /session/prepare
POST /mvc/start
POST /mvc/finish
POST /mvc/start
POST /mvc/finish
POST /mvc/start
POST /mvc/finish
POST /trial/start
GET /trial/status
GET /result/latest
```

