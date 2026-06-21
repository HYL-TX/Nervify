# backend/serial_io.py
#
# Everything that talks to the ESP32 over the serial port: tolerant line
# parsing, connection-state bookkeeping, and the background reader thread that
# feeds parsed samples into the session via session.add_sample.

import json
import queue
import re
import threading
import time

from . import config, session, state
from .utils import iso_now, parse_float

try:
    import serial
except ImportError:  # Allows tests/imports to run without pyserial installed.
    serial = None


# Commands queued by request handlers (e.g. "TARE") for the reader thread to
# write back to the device. We never write to the pyserial handle from the
# request thread -- only the reader thread owns `ser` -- so the handoff is this
# thread-safe queue, drained once per reader loop.
_outbound_commands: "queue.Queue[str]" = queue.Queue()


def queue_command(command: str) -> None:
    """Enqueue a one-line command to send to the device on the next reader loop."""

    _outbound_commands.put(command)
    with state.lock:
        state.serial_status["last_command"] = command
        state.serial_status["last_command_at"] = iso_now()


def _flush_outbound(ser) -> None:
    """Write any queued commands to the device, one newline-terminated line each."""

    try:
        while True:
            command = _outbound_commands.get_nowait()
            ser.write((command + "\n").encode())
    except queue.Empty:
        pass


def parse_serial_line(line: str):
    text = line.strip()
    if not text:
        return None

    # Fast path: a well-formed JSON line (the normal ESP32 output) parses
    # immediately, so the regex-repair work below is skipped at ~500 Hz.
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    # Repair common serial framing/key-quote glitches from partial device lines.
    # Example seen from ESP32 stream: {force":-0.60,"emg":197}
    repaired_text = re.sub(r"([{,]\s*)(force|force_n|emg|emg_rms)(\"\s*:)", r'\1"\2\3', text)

    try:
        payload = json.loads(repaired_text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    # Accept debug lines that include a JSON object, e.g. "DATA { ... }".
    for candidate in (text, repaired_text):
        json_start = candidate.find("{")
        json_end = candidate.rfind("}")
        if 0 <= json_start < json_end:
            snippet = candidate[json_start : json_end + 1]
            snippet = re.sub(
                r"([{,]\s*)(force|force_n|emg|emg_rms)(\"\s*:)",
                r'\1"\2\3',
                snippet,
            )
            try:
                payload = json.loads(snippet)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass

    lower_text = text.lower()
    labeled_values: dict[str, float] = {}
    for key, value in re.findall(
        r"\"?\b(force|force_n|emg|emg_rms)\b\"?\s*[:=]\s*(-?\d+(?:\.\d+)?)",
        lower_text,
    ):
        labeled_values[key] = float(value)

    if labeled_values:
        return labeled_values

    numeric_pair = re.fullmatch(
        r"\s*(-?\d+(?:\.\d+)?)\s*[, \t]\s*(-?\d+(?:\.\d+)?)\s*",
        text,
    )
    if numeric_pair:
        force, emg = numeric_pair.groups()
        return {"force": float(force), "emg": float(emg)}

    return None


def record_raw_serial_line(line: str) -> None:
    with state.lock:
        state.raw_serial_lines.append({"timestamp": iso_now(), "line": line})
        state.serial_status["last_line"] = line


def reject_serial_line(message: str) -> None:
    with state.lock:
        state.serial_status["last_parse_error"] = message
        state.serial_status["lines_rejected"] += 1


def accept_serial_sample() -> None:
    with state.lock:
        state.serial_status.update(
            {
                "connected": True,
                "last_error": None,
                "last_parse_error": None,
                "samples_received": state.serial_status["samples_received"] + 1,
                "last_sample_at": time.time(),
            }
        )


def serial_is_live() -> bool:
    """True only if a real sample arrived within SAMPLE_FRESHNESS_SECONDS.

    This is what the UI should trust: the raw `connected` handle flips on every
    transient read hiccup or reopen, but as long as data keeps flowing the
    device is effectively connected and the dashboard shouldn't flicker.
    """

    last = state.serial_status.get("last_sample_at")
    return last is not None and (time.time() - last) <= config.SAMPLE_FRESHNESS_SECONDS


def process_serial_line(line: str) -> None:
    record_raw_serial_line(line)
    payload = parse_serial_line(line)
    if payload is None:
        reject_serial_line("Could not find force/emg values.")
        return

    force = parse_float(payload, "force", "force_n", "Force_N")
    emg = parse_float(payload, "emg", "emg_rms", "EMG")
    if force is None or emg is None:
        reject_serial_line("Parsed line did not include both force and emg.")
        return

    session.add_sample(force, emg, payload)
    accept_serial_sample()


def serial_reader() -> None:
    if serial is None:
        state.serial_status["last_error"] = "pyserial is not installed."
        return

    ser = None
    pending_text = ""
    # macOS USB-CDC raises a spurious "ready to read but returned no data"
    # roughly once a second. Tearing the port down on a single such glitch
    # stalls the stream and tanks the sample rate, so only a run of back-to-back
    # failures (a genuine disconnect) triggers a reconnect.
    consecutive_errors = 0
    MAX_TRANSIENT_ERRORS = 5

    while True:
        if ser is None or not ser.is_open:
            try:
                # NOTE: leave DTR asserted (pyserial's default). This board uses
                # the ESP32 native USB-CDC, which only transmits while the host
                # holds DTR high -- forcing DTR low here makes Serial.print on
                # the device a silent no-op and no samples ever arrive.
                ser = serial.Serial(config.SERIAL_PORT, config.BAUD_RATE, timeout=1)
            except Exception as exc:
                with state.lock:
                    state.serial_status.update(
                        {
                            "connected": False,
                            "last_error": str(exc),
                            "read_errors": state.serial_status["read_errors"] + 1,
                        }
                    )
                time.sleep(1)  # device is absent; wait before retrying
                continue
            pending_text = ""
            consecutive_errors = 0
            with state.lock:
                state.serial_status.update(
                    {
                        "connected": True,
                        "last_error": None,
                        "last_connected_at": iso_now(),
                    }
                )

        try:
            # Send any commands queued by request handlers (e.g. a tare) before
            # reading. A write failure falls through to the same transient-error
            # handling as a read failure below.
            _flush_outbound(ser)

            # Read only what is actually buffered. Calling read() with a known
            # byte count avoids the blocking read(1) path where pyserial's
            # select() reports readiness but os.read() returns nothing -- the
            # source of the spurious macOS disconnect.
            waiting = ser.in_waiting
            if not waiting:
                time.sleep(0.002)
                continue

            chunk = ser.read(waiting)
            if not chunk:
                continue
            consecutive_errors = 0

            pending_text += chunk.decode(errors="ignore")
            parts = re.split(r"[\r\n]+", pending_text)
            if pending_text.endswith(("\r", "\n")):
                pending_text = ""
            else:
                pending_text = parts.pop()

            for line in parts:
                line = line.strip()
                if line:
                    process_serial_line(line)
        except Exception as exc:
            consecutive_errors += 1
            with state.lock:
                state.serial_status.update(
                    {
                        "last_error": str(exc),
                        "read_errors": state.serial_status["read_errors"] + 1,
                    }
                )
            if consecutive_errors >= MAX_TRANSIENT_ERRORS:
                # Sustained failures: the device really went away. Drop the port
                # and reconnect on the next loop.
                with state.lock:
                    state.serial_status["connected"] = False
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                time.sleep(0.5)
            else:
                time.sleep(0.01)  # ride out a transient glitch, keep the port


def start_serial_reader() -> None:
    """Launch the serial reader on a daemon thread."""

    threading.Thread(target=serial_reader, daemon=True).start()
