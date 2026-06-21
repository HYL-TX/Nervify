# test_serial.py

import serial

ser = serial.Serial(
    "/dev/cu.usbmodem14101",
    115200,
    timeout=1
)

print("Connected!")

while True:
    line = ser.readline().decode(errors="ignore").strip()

    if line:
        print(line)
