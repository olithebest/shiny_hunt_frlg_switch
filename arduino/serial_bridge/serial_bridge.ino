/*
 * Serial Bridge — Sender Arduino
 * ==============================
 * Upload this to any regular Arduino (Uno, Nano, Mega, etc.)
 * This Arduino connects to your PC via USB and relays commands to the Pro Micro.
 *
 * WIRING (3 wires between this Arduino and the Pro Micro)
 * -------------------------------------------------------
 *   This Arduino D11  (TX_SW)  →  Pro Micro pin 0  (RX1)
 *   This Arduino D10  (RX_SW)  ←  Pro Micro pin 1  (TX1)
 *   This Arduino GND           ↔  Pro Micro GND     ← REQUIRED!
 *
 * HOW IT WORKS
 * ------------
 * Python sends "PRESS A 200\n" to this Arduino's COM port (USB serial).
 * This Arduino forwards every byte to the Pro Micro over SoftwareSerial (pins 10/11).
 * The Pro Micro executes the command and sends "OK A\n" back.
 * This Arduino relays the response back to Python.
 *
 * BAUD RATES
 * ----------
 *   USB (PC ↔ this Arduino) : 9600
 *   Wire (this ↔ Pro Micro) : 9600
 *
 * NOTE: If you have an Arduino Mega, you can use Serial1 (pins 18/19) instead of
 * SoftwareSerial — just swap the SoftwareSerial lines for Serial1.
 */

#include <SoftwareSerial.h>

// Pin 10 = RX (receives data FROM Pro Micro TX1)
// Pin 11 = TX (sends data TO Pro Micro RX1)
SoftwareSerial proMicro(10, 11);

void setup() {
  Serial.begin(9600);    // PC <-> this Arduino (USB)
  proMicro.begin(9600);  // this Arduino <-> Pro Micro (wires)
}

void loop() {
  // Forward bytes from PC to Pro Micro
  if (Serial.available()) {
    proMicro.write(Serial.read());
  }
  // Forward bytes from Pro Micro back to PC (responses like "OK A", "READY")
  if (proMicro.available()) {
    Serial.write(proMicro.read());
  }
}
