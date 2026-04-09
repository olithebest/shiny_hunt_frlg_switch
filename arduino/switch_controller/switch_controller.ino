/*
 * Shiny Hunter FRLG — Arduino Switch Controller
 * ==============================================
 * Hardware : Arduino Pro Micro  OR  Arduino Leonardo (ATmega32U4)
 * Library  : NintendoSwitchControlLibrary
 *            Install via: Arduino IDE → Sketch → Include Library
 *                         → Manage Libraries → search "NintendoSwitchControlLibrary"
 *            GitHub: https://github.com/lefmarna/NintendoSwitchControlLibrary
 *
 * HOW TO FLASH
 * ------------
 * 1. Install Arduino IDE from https://www.arduino.cc/en/software
 * 2. Install NintendoSwitchControlLibrary via Library Manager (see above)
 * 3. Tools → Board → Arduino Leonardo  (works for both Leonardo and Pro Micro)
 *    (For Pro Micro: install "SparkFun AVR Boards" via Board Manager first)
 * 4. Tools → Port → select the COM port for your Arduino
 * 5. Sketch → Upload
 * 6. Unplug Arduino from PC
 * 7. Plug Arduino into Nintendo Switch dock USB port
 * 8. Switch 2 will recognize it as a wired Pro Controller
 * 9. Plug Arduino back into PC — the PC sends button commands, Arduino forwards them to Switch
 *
 * SERIAL PROTOCOL  (9600 baud, newline-terminated)
 * ------------------------------------------------
 *   PRESS <BUTTON> <DURATION_MS>\n
 *   SOFT_RESET\n
 *
 *   Buttons: A B X Y L R ZL ZR PLUS MINUS HOME UP DOWN LEFT RIGHT
 *
 * DUAL-ARDUINO WIRING
 * -------------------
 * Pro Micro pin 0 (RX1) ← Sender Arduino TX pin (D11 if using SoftwareSerial)
 * Pro Micro pin 1 (TX1) → Sender Arduino RX pin (D10 if using SoftwareSerial)
 * Pro Micro GND         ↔ Sender Arduino GND  (REQUIRED — common ground)
 *
 * The sender Arduino (Uno/Nano/etc.) runs serial_bridge.ino and connects
 * to the PC via USB. Python talks to the sender, sender relays to this sketch.
 *
 * IMPORTANT NOTES
 * ---------------
 * - This sketch uses Serial1 (hardware UART pins 0/1), NOT the USB serial port
 * - The USB port on the Pro Micro is dedicated to the Switch HID connection
 * - Plug Pro Micro into Switch dock, sender Arduino into PC USB
 */

#include <NintendoSwitchControlLibrary.h>

String inputBuffer = "";

// ------------------------------------------------------------------
// Button name → uint16_t value (Button:: constants are uint16_t)
// ------------------------------------------------------------------
uint16_t nameToButton(const String& name) {
  if (name == "A")     return Button::A;
  if (name == "B")     return Button::B;
  if (name == "X")     return Button::X;
  if (name == "Y")     return Button::Y;
  if (name == "L")     return Button::L;
  if (name == "R")     return Button::R;
  if (name == "ZL")    return Button::ZL;
  if (name == "ZR")    return Button::ZR;
  if (name == "PLUS")  return Button::PLUS;
  if (name == "MINUS") return Button::MINUS;
  if (name == "HOME")  return Button::HOME;
  return Button::A;
}

// Hat:: constants are uint8_t; UP/DOWN not TOP/BOTTOM
uint8_t nameToHat(const String& name) {
  if (name == "UP")    return Hat::UP;
  if (name == "DOWN")  return Hat::DOWN;
  if (name == "LEFT")  return Hat::LEFT;
  if (name == "RIGHT") return Hat::RIGHT;
  return Hat::NEUTRAL;
}

bool isDpad(const String& name) {
  return name == "UP" || name == "DOWN" || name == "LEFT" || name == "RIGHT";
}

bool isKnownButton(const String& name) {
  return name == "A" || name == "B" || name == "X" || name == "Y" ||
         name == "L" || name == "R" || name == "ZL" || name == "ZR" ||
         name == "PLUS" || name == "MINUS" || name == "HOME";
}

// ------------------------------------------------------------------
// Press helpers
// ------------------------------------------------------------------
void pressButton(const String& name, int duration_ms) {
  uint16_t btn = nameToButton(name);
  SwitchControlLibrary().pressButton(btn);
  SwitchControlLibrary().sendReport();
  delay(duration_ms);
  SwitchControlLibrary().releaseButton(btn);
  SwitchControlLibrary().sendReport();
  delay(50);
}

void pressDpad(const String& name, int duration_ms) {
  uint8_t hat = nameToHat(name);
  SwitchControlLibrary().pressHatButton(hat);
  SwitchControlLibrary().sendReport();
  delay(duration_ms);
  SwitchControlLibrary().releaseHatButton();
  SwitchControlLibrary().sendReport();
  delay(50);
}

// GBA NSO soft reset: A + B + X + Y held simultaneously
void softReset() {
  SwitchControlLibrary().pressButton(Button::A);
  SwitchControlLibrary().pressButton(Button::B);
  SwitchControlLibrary().pressButton(Button::X);
  SwitchControlLibrary().pressButton(Button::Y);
  SwitchControlLibrary().sendReport();
  delay(500);
  SwitchControlLibrary().releaseButton(Button::A);
  SwitchControlLibrary().releaseButton(Button::B);
  SwitchControlLibrary().releaseButton(Button::X);
  SwitchControlLibrary().releaseButton(Button::Y);
  SwitchControlLibrary().sendReport();
  delay(200);
}

// ------------------------------------------------------------------
// Setup
// ------------------------------------------------------------------
void setup() {
  Serial1.begin(9600);  // UART to sender Arduino (pins 0=RX, 1=TX)
                        // NOT Serial (USB) — that port belongs to the Switch
  // Register controller with Switch (same pattern that works in controller_test)
  pushButton(Button::L, 500, 5);
  Serial1.println("READY");
}

// ------------------------------------------------------------------
// Main loop — reads serial commands from sender Arduino
// ------------------------------------------------------------------
void loop() {
  while (Serial1.available()) {
    char c = (char)Serial1.read();

    if (c == '\n') {
      inputBuffer.trim();

      if (inputBuffer.length() == 0) {
        inputBuffer = "";
        continue;
      }

      if (inputBuffer == "SOFT_RESET") {
        softReset();
        Serial1.println("OK SOFT_RESET");

      } else if (inputBuffer.startsWith("PRESS ")) {
        String rest     = inputBuffer.substring(6);
        int    spaceIdx = rest.indexOf(' ');
        String btnName  = (spaceIdx > 0) ? rest.substring(0, spaceIdx) : rest;
        int    duration = (spaceIdx > 0) ? rest.substring(spaceIdx + 1).toInt() : 100;

        if (duration <= 0 || duration > 5000) duration = 100; // safety clamp

        if (isDpad(btnName)) {
          pressDpad(btnName, duration);
          Serial1.println("OK " + btnName);
        } else if (isKnownButton(btnName)) {
          pressButton(btnName, duration);
          Serial1.println("OK " + btnName);
        } else {
          Serial1.println("ERR Unknown button: " + btnName);
        }

      } else {
        Serial1.println("ERR Unknown command: " + inputBuffer);
      }

      inputBuffer = "";

    } else {
      if (inputBuffer.length() < 64) {
        inputBuffer += c;
      }
    }
  }
}
