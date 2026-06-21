#include <HX711.h>

// ---------------------------------------------------------------------------
// Nervify ESP32 firmware
//
// Streams one JSON object per line over USB serial, e.g.
//   {"force":2.95,"emg":189}
// which the FastAPI backend parses in backend/serial_io.py.
//
// It also accepts one command back from the host: a line reading "TARE"
// re-zeros the load cell (scale.tare()). The backend sends this when the
// operator presses "Tare load cell" in Device Setup; keep the cell unloaded.
//
// Key design point: EMG must be sampled fast (the backend's 60 Hz notch
// filter only engages above ~120 Hz, and it splits each 3 s trial into six
// 0.5 s RMS windows). The HX711 load cell only updates at ~80 Hz, so we must
// NOT let it block the EMG read. We poll the HX711 non-blocking and hold the
// last force value between updates, while EMG streams as fast as the loop runs.
// ---------------------------------------------------------------------------

#define EMG_PIN A0   // ESP32: A0 is typically GPIO36 (ADC1, input-only) - OK

#define DT D4
#define SCK D5

HX711 scale;

// IMPORTANT: get_units() must return NEWTONS. The backend labels and stores
// force as Newtons throughout, so the units must be right here at the source.
//
// This load cell + board reads ~418 counts per gram. We divide that grams
// factor by grams-per-Newton (1000 / 9.80665) to get counts-per-Newton, so
// get_units() comes out in Newtons:
//   counts/N = 418.0 * 1000 / 9.80665  ≈  42624
//
// To re-calibrate: place a known mass and adjust COUNTS_PER_GRAM until the
// grams readout in the UI matches the mass (the backend reading should then
// equal mass_kg * 9.80665 Newtons).
const float COUNTS_PER_GRAM = 418.0;                 // measured for this load cell
const float GRAMS_PER_NEWTON = 1000.0 / 9.80665;     // 1 N ≈ 101.97 g
float calibration_factor = COUNTS_PER_GRAM * GRAMS_PER_NEWTON;  // counts per Newton

// Force is sampled at ~80 Hz (HX711 hardware limit); EMG streams every loop.
const unsigned long FORCE_INTERVAL_MS = 12;   // ~80 Hz
unsigned long lastForceTime = 0;
float lastForce = 0.0;

void setup()
{
    Serial.begin(115200);

    scale.begin(DT, SCK);
    scale.set_scale(calibration_factor);

    // Tare requires the load cell to be UNLOADED at power-on, or the zero
    // baseline (and thus every force reading this session) will be wrong.
    scale.tare();
}

void loop()
{
    // --- Commands from host: a line reading "TARE" re-zeros the load cell ---
    // Reading is non-blocking (only drains what's already buffered) so it never
    // stalls the EMG stream. The host must keep the cell unloaded when taring,
    // exactly like the power-on tare in setup().
    static String command;
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            command.trim();
            if (command == "TARE") {
                scale.tare();
            }
            command = "";
        } else if (command.length() < 32) {   // bound the buffer against noise
            command += c;
        }
    }

    // --- Force: poll HX711 only when fresh data is ready (non-blocking) ---
    if (millis() - lastForceTime >= FORCE_INTERVAL_MS && scale.is_ready()) {
        lastForce = scale.get_units(1);   // single read; get_units(3) blocks ~37 ms
        lastForceTime = millis();
    }

    // --- EMG: fast read every loop iteration ---
    int emg = analogRead(EMG_PIN);

    // --- Emit one JSON object per line (matches backend parser) ---
    Serial.print("{\"force\":");
    Serial.print(lastForce);
    Serial.print(",\"emg\":");
    Serial.print(emg);
    Serial.println("}");

    // ~500 Hz loop. Above the backend's 120 Hz notch threshold and enough to
    // fill the six 0.5 s EMG RMS windows. Lower if your serial link can't keep up.
    delayMicroseconds(2000);
}
