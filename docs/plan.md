# Code Logic Summary: NME Measurement Pipeline

## Overall Goal
The system measures thumb muscle performance by recording force and EMG signals during a controlled contraction. It then calculates Neuromuscular Efficiency (NME) and stores the result so patient recovery can be tracked over time.

---

## Step 0: One-Time Device Setup

### 0.1 Set target percentage
- Program the target contraction level into the ESP32.
- In this pipeline, the target is set to **20% MVC**.
- MVC means **Maximum Voluntary Contraction**.

### 0.2 Calibrate the load cell
- Place known weights on the load cell post.
- Read the ADC values from the load cell.
- Convert ADC readings into force values in Newtons.
- Save the calibration factor in ESP32 memory.

**Output:**
- Target percentage = 20%
- Load cell calibration factor

---

## Step 1: Session Preparation

### Purpose
Make sure the device and patient are ready before measurement.

### Logic
1. Prepare the skin by cleaning the thenar area with alcohol.
2. Place the EMG electrode on the APB muscle.
3. Mark the skin position to keep placement consistent across sessions.
4. Position the patient's hand correctly:
   - Palm down
   - Wrist neutral
   - Thumb aligned with the load cell post
   - Elbow around 90°

**Output:**
- Patient and device are ready for recording.

---

## Step 2: MVC Calibration

### Purpose
Find the patient's maximum force and maximum EMG activity for that session.

### Logic
1. Ask the patient to pinch the load cell post as hard as possible.
2. Hold the contraction for **3 seconds**.
3. Record force and EMG data during the attempt.
4. Let the patient rest for **60 seconds**.
5. Repeat this process **3 times**.
6. Select the highest force value as `MVC_Force`.
7. Select the highest EMG RMS value as `MVC_EMG`.
8. Calculate the target force:

```text
Target_Force = 20% × MVC_Force
```

**Output:**
- `MVC_Force`
- `MVC_EMG`
- `Target_Force`

---

## Step 3: Monitoring Contraction

### Purpose
Measure controlled muscle performance at the target force level.

### Logic
1. Show the target force on the screen.
2. Patient pinches the load cell post until the force reaches the target line.
3. Once the force is within the accepted range, start a 3-second timer.
4. The force must stay within ±10% of the target force.
5. If the force drops outside the range, reset the timer.
6. Accept the trial only if the force remains stable for the full 3 seconds.

### Acceptance rule
```text
Accept if:
Force_N ≥ Target_Force × 0.90
AND
Force_N ≤ Target_Force × 1.10
AND
Force is stable for 3 seconds
```

**Output:**
- Valid 3-second monitoring contraction data

---

## Step 4: Real-Time Signal Processing

### Purpose
Convert raw EMG and force signals into usable values.

### EMG signal logic
1. MyoWare sensor outputs the EMG envelope signal.
2. ESP32 reads EMG data using ADC at around **1000 Hz**.
3. Apply a 60 Hz notch filter to reduce electrical noise.
4. Split the 3-second recording into six 0.5-second windows.
5. Calculate RMS for each window.
6. Average the six RMS values.

```text
Total_EMG_RMS = mean of 6 window RMS values
```

### Force signal logic
1. HX711 reads the load cell signal at around **80 Hz**.
2. Apply a low-pass filter at around **10 Hz**.
3. Convert load cell readings into Newtons using the calibration factor.
4. Average the force across the 3-second window.

```text
Force_N = mean force over 3 seconds
```

**Output:**
- `Total_EMG_RMS`
- `Force_N`

---

## Step 5: NME Calculation

### Purpose
Calculate Neuromuscular Efficiency using normalized force and EMG values.

### Logic
1. Normalize force to the session MVC force.
2. Normalize EMG to the session MVC EMG.
3. Calculate NME by dividing normalized force by normalized EMG.

```text
%MVC_Force = (Force_N / MVC_Force) × 100
%MVC_EMG = (Total_EMG_RMS / MVC_EMG) × 100
NME = %MVC_Force / %MVC_EMG
```

### Why normalization is important
Raw force and raw EMG have different units and vary between patients. Normalizing both values to each patient's MVC makes the result easier to compare across sessions.

**Output:**
- `%MVC_Force`
- `%MVC_EMG`
- `NME`

---

## Step 6: Store and Display Results

### Purpose
Save the session result and show recovery progress over time.

### Logic
1. Save the session data with a timestamp.
2. Store key values:
   - `MVC_Force`
   - `MVC_EMG`
   - `Force_N`
   - `Total_EMG_RMS`
   - `NME`
3. Display the current NME value on the screen.
4. Compare with the previous session.
5. Show a trend arrow:
   - ↑ improved
   - ↓ decreased
   - → stable

**Output:**
- Session log
- Current NME result
- Progress trend

---

## Full Logic Flow

```text
Start
↓
One-time setup
↓
Prepare skin, electrode, and hand position
↓
Record 3 MVC attempts
↓
Save highest MVC force and EMG
↓
Calculate 20% target force
↓
Patient performs controlled 3-second contraction
↓
Check force stays within ±10% target
↓
Process EMG and force signals
↓
Calculate %MVC force and %MVC EMG
↓
Calculate NME
↓
Save and display result
↓
Compare with previous session
End
```

---

## Short Summary
The code first calibrates the device and patient baseline, then guides the patient to perform a controlled 20% MVC contraction. During the contraction, the ESP32 records EMG and force signals, processes them into RMS EMG and average force, calculates NME using normalized values, and stores the result to track recovery across sessions.
