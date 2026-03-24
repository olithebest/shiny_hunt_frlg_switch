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
 * IMPORTANT NOTES
 * ---------------
 * - The Switch 2 must be awake before starting — cannot be powered on remotely
 * - Plug Arduino into Switch BEFORE booting, or use Change Grip/Order to register
 * - Switch 2 does NOT require extra pairing steps for USB HID controllers
 */

#include <NintendoSwitchControlLibrary.h>

String inputBuffer = "";

// ------------------------------------------------------------------
// Button name → library enum
// ------------------------------------------------------------------
Button nameToButton(const String& name) {
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
  return Button::A; // fallback
}

Hat nameToHat(const String& name) {
  if (name == "UP")    return Hat::TOP;
  if (name == "DOWN")  return Hat::BOTTOM;
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
  Button btn = nameToButton(name);
  SwitchControlLibrary().pressButton(btn);
  SwitchControlLibrary().sendReport();
  delay(duration_ms);
  SwitchControlLibrary().releaseButton(btn);
  SwitchControlLibrary().sendReport();
  delay(50);
}

void pressDpad(const String& name, int duration_ms) {
  Hat hat = nameToHat(name);
  SwitchControlLibrary().moveHat(hat);
  SwitchControlLibrary().sendReport();
  delay(duration_ms);
  SwitchControlLibrary().moveHat(Hat::NEUTRAL);
  SwitchControlLibrary().sendReport();
  delay(50);
}

// GBA NSO soft reset: ZL + ZR + PLUS + MINUS held simultaneously
void softReset() {
  SwitchControlLibrary().pressButton(Button::ZL);
  SwitchControlLibrary().pressButton(Button::ZR);
  SwitchControlLibrary().pressButton(Button::PLUS);
  SwitchControlLibrary().pressButton(Button::MINUS);
  SwitchControlLibrary().sendReport();
  delay(300);
  SwitchControlLibrary().releaseButton(Button::ZL);
  SwitchControlLibrary().releaseButton(Button::ZR);
  SwitchControlLibrary().releaseButton(Button::PLUS);
  SwitchControlLibrary().releaseButton(Button::MINUS);
  SwitchControlLibrary().sendReport();
  delay(200);
}

// ------------------------------------------------------------------
// Setup
// ------------------------------------------------------------------
void setup() {
  Serial.begin(9600);
  delay(3000); // Give Switch time to register the controller
  SwitchControlLibrary().sendReport(); // neutral state
  delay(500);
  Serial.println("READY");
}

// ------------------------------------------------------------------
// Main loop — reads serial commands from PC
// ------------------------------------------------------------------
void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();

    if (c == '\n') {
      inputBuffer.trim();

      if (inputBuffer.length() == 0) {
        inputBuffer = "";
        continue;
      }

      if (inputBuffer == "SOFT_RESET") {
        softReset();
        Serial.println("OK SOFT_RESET");

      } else if (inputBuffer.startsWith("PRESS ")) {
        String rest     = inputBuffer.substring(6);
        int    spaceIdx = rest.indexOf(' ');
        String btnName  = (spaceIdx > 0) ? rest.substring(0, spaceIdx) : rest;
        int    duration = (spaceIdx > 0) ? rest.substring(spaceIdx + 1).toInt() : 100;

        if (duration <= 0 || duration > 5000) duration = 100; // safety clamp

        if (isDpad(btnName)) {
          pressDpad(btnName, duration);
          Serial.println("OK " + btnName);
        } else if (isKnownButton(btnName)) {
          pressButton(btnName, duration);
          Serial.println("OK " + btnName);
        } else {
          Serial.println("ERR Unknown button: " + btnName);
        }

      } else {
        Serial.println("ERR Unknown command: " + inputBuffer);
      }

      inputBuffer = "";

    } else {
      if (inputBuffer.length() < 64) {
        inputBuffer += c;
      }
    }
  }
}
