/*
 * Shiny Hunter FRLG — Arduino Switch Controller
 * ==============================================
 * Hardware : Arduino Leonardo  OR  Pro Micro (ATmega32U4)
 * Purpose  : Enumerates as a Nintendo Switch Pro Controller via USB HID.
 *            Receives simple ASCII commands from the PC over Serial and
 *            translates them into HID button reports.
 *
 * SETUP
 * -----
 * 1. Install Arduino IDE (https://www.arduino.cc/en/software)
 * 2. Install the "NintendoSwitchControlLibrary" or "NSGamepad" library
 *    via Sketch → Include Library → Manage Libraries.
 * 3. Select board: Tools → Board → Arduino Leonardo (or Pro Micro)
 * 4. Upload this sketch.
 * 5. Unplug & replug the Arduino into the Nintendo Switch USB port.
 * 6. In the app, set Controller Mode to "Serial (Arduino)" and
 *    enter the correct COM port.
 *
 * SERIAL PROTOCOL  (9600 baud, newline-terminated)
 * ------------------------------------------------
 *   PRESS <BUTTON> <DURATION_MS>\n   — press a button for N milliseconds
 *   SOFT_RESET\n                     — hold ZL+ZR+PLUS+MINUS for 300 ms
 *
 *   Supported buttons: A B X Y L R ZL ZR PLUS MINUS HOME
 *                      UP DOWN LEFT RIGHT
 *
 * NOTE: This sketch is a template. Adjust the HID library calls below
 * to match whichever Switch HID library you installed.
 */

// ---- Replace with your library's include & class -------------------------
// Example using "NSGamepad" library:
//   #include <NSGamepad.h>
// -------------------------------------------------------------------------

String inputBuffer = "";

// ---- Button bit masks (Pro Controller HID report) -----------------------
#define BTN_A      (1 << 3)
#define BTN_B      (1 << 2)
#define BTN_X      (1 << 4)
#define BTN_Y      (1 << 1)
#define BTN_L      (1 << 6)
#define BTN_R      (1 << 7)
#define BTN_ZL     (1 << 8)
#define BTN_ZR     (1 << 9)
#define BTN_PLUS   (1 << 10)
#define BTN_MINUS  (1 << 11)
#define BTN_HOME   (1 << 12)

void setup() {
  Serial.begin(9600);
  // Initialize your HID library here, e.g.:
  //   NSGamepad.begin();
  delay(2000);
  Serial.println("READY");
}

uint16_t nameToButton(const String& name) {
  if (name == "A")     return BTN_A;
  if (name == "B")     return BTN_B;
  if (name == "X")     return BTN_X;
  if (name == "Y")     return BTN_Y;
  if (name == "L")     return BTN_L;
  if (name == "R")     return BTN_R;
  if (name == "ZL")    return BTN_ZL;
  if (name == "ZR")    return BTN_ZR;
  if (name == "PLUS")  return BTN_PLUS;
  if (name == "MINUS") return BTN_MINUS;
  if (name == "HOME")  return BTN_HOME;
  return 0;
}

void pressButton(uint16_t btn, int duration_ms) {
  // Adapt to your library. Example with NSGamepad:
  //   NSGamepad.press(btn);
  //   delay(duration_ms);
  //   NSGamepad.release(btn);
  //   NSGamepad.loop();
  delay(duration_ms);  // placeholder until library is wired up
}

void pressDpad(const String& dir, int duration_ms) {
  // Adapt to your library for D-pad / hat switch
  // e.g. NSGamepad.dPad(DPAD_UP); delay(ms); NSGamepad.dPad(DPAD_CENTERED);
  delay(duration_ms);
}

void softReset() {
  // Hold ZL + ZR + PLUS + MINUS simultaneously for 300 ms
  // Adapt: NSGamepad.press(BTN_ZL | BTN_ZR | BTN_PLUS | BTN_MINUS);
  delay(300);
  // NSGamepad.releaseAll();
  // NSGamepad.loop();
  delay(200);
}

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
        // Format: "PRESS <BUTTON> <DURATION_MS>"
        String rest     = inputBuffer.substring(6);
        int    spaceIdx = rest.indexOf(' ');
        String btnName  = (spaceIdx > 0) ? rest.substring(0, spaceIdx)  : rest;
        int    duration = (spaceIdx > 0) ? rest.substring(spaceIdx + 1).toInt() : 100;

        // D-pad directions handled separately
        if (btnName == "UP" || btnName == "DOWN" ||
            btnName == "LEFT" || btnName == "RIGHT") {
          pressDpad(btnName, duration);
          Serial.println("OK " + btnName);
        } else {
          uint16_t btn = nameToButton(btnName);
          if (btn != 0) {
            pressButton(btn, duration);
            Serial.println("OK " + btnName);
          } else {
            Serial.println("ERR Unknown: " + btnName);
          }
        }
      } else {
        Serial.println("ERR Unknown command: " + inputBuffer);
      }

      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }
}
