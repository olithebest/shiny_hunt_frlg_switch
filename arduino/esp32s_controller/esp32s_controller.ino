/*
 * Shiny Hunter — ESP32-S2 / ESP32-S3 Nintendo Switch Controller
 * =============================================================
 * Drop-in replacement for the Arduino Pro Micro in the controller chain.
 * The ESP32-S2/S3 has native USB-OTG hardware that can emulate a HID
 * game controller, unlike the original ESP32 which has no native USB.
 *
 * WHAT EACH DEVICE DOES
 * ---------------------
 *   PC (Python)  ──USB──►  serial_bridge Arduino (serial_bridge.ino)
 *                                │
 *                            UART TX ──►  ESP32-S2/S3  RX (GPIO 18)
 *                                              │
 *                                          USB HID ──►  Nintendo Switch dock
 *
 *   The serial_bridge Arduino relays PC commands over hardware UART to this
 *   sketch, which converts them to USB HID reports for the Switch.
 *   (Same wiring as the Pro Micro, pins are different — see below.)
 *
 * WIRING
 * ------
 *   serial_bridge Arduino TX  ──►  ESP32-S2/S3  GPIO 18  (Serial1 RX)
 *   serial_bridge Arduino GND ───  ESP32-S2/S3  GND      (REQUIRED)
 *   ESP32-S2/S3  USB connector ──► Nintendo Switch dock USB port
 *
 *   NOTE: Do NOT connect the serial_bridge Arduino TX to the ESP32 USB pins.
 *         Use GPIO 18 (UART RX) for receiving commands.
 *
 * ARDUINO IDE SETUP
 * -----------------
 *   1. Install ESP32 board support:
 *      File → Preferences → Additional Board URLs:
 *        https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
 *      Then: Tools → Board Manager → search "esp32" → install "esp32 by Espressif Systems" v2.x
 *
 *   2. Select your board:
 *      - For ESP32-S2: Tools → Board → ESP32S2 Dev Module
 *      - For ESP32-S3: Tools → Board → ESP32S3 Dev Module
 *
 *   3. Set USB options:
 *      Tools → USB CDC On Boot  → Disabled
 *      Tools → USB Mode         → USB-OTG (TinyUSB)
 *
 *   4. Upload, then unplug from PC and plug into Switch dock.
 *
 * SERIAL PROTOCOL (same as Pro Micro version — 9600 baud, newline-terminated)
 * ---------------------------------------------------------------------------
 *   PRESS <BUTTON> <DURATION_MS>\n
 *   SOFT_RESET\n
 *
 *   Buttons: A B X Y L R ZL ZR PLUS MINUS HOME UP DOWN LEFT RIGHT
 *
 * TESTED ON
 * ---------
 *   ESP32-S2-DevKitC-1, ESP32-S3-DevKitC-1
 *   Arduino ESP32 core 2.0.14
 */

#include "USB.h"
#include "USBHID.h"

// ---------------------------------------------------------------------------
// HID descriptor — matches what the Nintendo Switch expects from a HORIPAD S
// (VID 0x0F0D / PID 0x00C1). This is the same descriptor used by the
// NintendoSwitchControlLibrary on AVR.
// ---------------------------------------------------------------------------
static const uint8_t SWITCH_HID_DESC[] = {
  0x05, 0x01,        // Usage Page (Generic Desktop)
  0x09, 0x05,        // Usage (Game Pad)
  0xA1, 0x01,        // Collection (Application)
  0x15, 0x00,        //   Logical Minimum (0)
  0x25, 0x01,        //   Logical Maximum (1)
  0x35, 0x00,        //   Physical Minimum (0)
  0x45, 0x01,        //   Physical Maximum (1)
  0x75, 0x01,        //   Report Size (1)
  0x95, 0x0E,        //   Report Count (14) — 14 buttons
  0x05, 0x09,        //   Usage Page (Buttons)
  0x19, 0x01,        //   Usage Minimum (Button 1)
  0x29, 0x0E,        //   Usage Maximum (Button 14)
  0x81, 0x02,        //   Input (Data, Variable, Absolute)
  0x95, 0x02,        //   Report Count (2) — 2 padding bits
  0x81, 0x01,        //   Input (Constant)
  0x05, 0x01,        //   Usage Page (Generic Desktop)
  0x25, 0x07,        //   Logical Maximum (7)
  0x46, 0x3B, 0x01,  //   Physical Maximum (315)
  0x75, 0x04,        //   Report Size (4)
  0x95, 0x01,        //   Report Count (1)
  0x65, 0x14,        //   Unit (Eng Rot, Angular Pos)
  0x09, 0x39,        //   Usage (Hat Switch)
  0x81, 0x42,        //   Input (Data, Variable, Absolute, Null)
  0x65, 0x00,        //   Unit (None)
  0x95, 0x01,        //   Report Count (1) — hat padding
  0x81, 0x01,        //   Input (Constant)
  0x26, 0xFF, 0x00,  //   Logical Maximum (255)
  0x46, 0xFF, 0x00,  //   Physical Maximum (255)
  0x09, 0x30,        //   Usage (X)   — Left stick X
  0x09, 0x31,        //   Usage (Y)   — Left stick Y
  0x09, 0x32,        //   Usage (Z)   — Right stick X
  0x09, 0x35,        //   Usage (Rz)  — Right stick Y
  0x75, 0x08,        //   Report Size (8)
  0x95, 0x04,        //   Report Count (4)
  0x81, 0x02,        //   Input (Data, Variable, Absolute)
  0xC0               // End Collection
};

// ---------------------------------------------------------------------------
// HID Report structure — 8 bytes total
// ---------------------------------------------------------------------------
struct __attribute__((packed)) SwitchReport {
  uint16_t buttons;  // bit 0..13 = buttons B Y X A R L ZR ZL MINUS PLUS HOME CAPTURE LCLICK RCLICK
  uint8_t  hat;      // 0=Up 1=UpRight 2=Right 3=DownRight 4=Down 5=DownLeft 6=Left 7=UpLeft 8=Neutral
  uint8_t  lx, ly;   // Left  stick (128 = center)
  uint8_t  rx, ry;   // Right stick (128 = center)
};

// Button bit positions (matching NintendoSwitchControlLibrary order)
#define BTN_Y      (1 << 0)
#define BTN_B      (1 << 1)
#define BTN_A      (1 << 2)
#define BTN_X      (1 << 3)
#define BTN_L      (1 << 4)
#define BTN_R      (1 << 5)
#define BTN_ZL     (1 << 6)
#define BTN_ZR     (1 << 7)
#define BTN_MINUS  (1 << 8)
#define BTN_PLUS   (1 << 9)
#define BTN_LCLICK (1 << 10)
#define BTN_RCLICK (1 << 11)
#define BTN_HOME   (1 << 12)
#define BTN_CAPTURE (1 << 13)

#define HAT_UP        0
#define HAT_UP_RIGHT  1
#define HAT_RIGHT     2
#define HAT_DOWN_RIGHT 3
#define HAT_DOWN      4
#define HAT_DOWN_LEFT 5
#define HAT_LEFT      6
#define HAT_UP_LEFT   7
#define HAT_NEUTRAL   8

// ---------------------------------------------------------------------------
// Custom HID device class
// ---------------------------------------------------------------------------
class SwitchController : public USBHIDDevice {
public:
  SwitchController() {}

  void begin() {
    static bool started = false;
    if (!started) {
      HID.addDevice(this, sizeof(SWITCH_HID_DESC));
      started = true;
    }
  }

  // Called by TinyUSB to get our HID descriptor
  uint16_t _onGetDescriptor(uint8_t* buf) override {
    memcpy(buf, SWITCH_HID_DESC, sizeof(SWITCH_HID_DESC));
    return sizeof(SWITCH_HID_DESC);
  }

  bool sendReport(SwitchReport* rpt) {
    return HID.SendReport(0, rpt, sizeof(SwitchReport));
  }

  // Neutral report — all buttons released, sticks centered
  void sendNeutral() {
    SwitchReport rpt = {0, HAT_NEUTRAL, 128, 128, 128, 128};
    sendReport(&rpt);
  }
};

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
USBHID        HID;
SwitchController controller;
SwitchReport  currentReport = {0, HAT_NEUTRAL, 128, 128, 128, 128};
String        inputBuffer   = "";

// ---------------------------------------------------------------------------
// Button / hat name helpers
// ---------------------------------------------------------------------------
bool isDpad(const String& name) {
  return name == "UP" || name == "DOWN" || name == "LEFT" || name == "RIGHT";
}

uint16_t nameToButton(const String& name) {
  if (name == "A")      return BTN_A;
  if (name == "B")      return BTN_B;
  if (name == "X")      return BTN_X;
  if (name == "Y")      return BTN_Y;
  if (name == "L")      return BTN_L;
  if (name == "R")      return BTN_R;
  if (name == "ZL")     return BTN_ZL;
  if (name == "ZR")     return BTN_ZR;
  if (name == "PLUS")   return BTN_PLUS;
  if (name == "MINUS")  return BTN_MINUS;
  if (name == "HOME")   return BTN_HOME;
  return BTN_A;
}

uint8_t nameToHat(const String& name) {
  if (name == "UP")    return HAT_UP;
  if (name == "DOWN")  return HAT_DOWN;
  if (name == "LEFT")  return HAT_LEFT;
  if (name == "RIGHT") return HAT_RIGHT;
  return HAT_NEUTRAL;
}

// ---------------------------------------------------------------------------
// Press helpers
// ---------------------------------------------------------------------------
void pressButton(const String& name, int duration_ms) {
  currentReport.buttons |= nameToButton(name);
  controller.sendReport(&currentReport);
  delay(duration_ms);
  currentReport.buttons &= ~nameToButton(name);
  controller.sendReport(&currentReport);
  delay(50);
}

void pressDpad(const String& name, int duration_ms) {
  currentReport.hat = nameToHat(name);
  controller.sendReport(&currentReport);
  delay(duration_ms);
  currentReport.hat = HAT_NEUTRAL;
  controller.sendReport(&currentReport);
  delay(50);
}

// GBA NSO soft reset: A + B + X + Y simultaneously
void softReset() {
  currentReport.buttons |= (BTN_A | BTN_B | BTN_X | BTN_Y);
  controller.sendReport(&currentReport);
  delay(500);
  currentReport.buttons &= ~(BTN_A | BTN_B | BTN_X | BTN_Y);
  controller.sendReport(&currentReport);
  delay(200);
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
void setup() {
  // USB device info — Switch will see this as a HORIPAD S
  USB.VID(0x0F0D);
  USB.PID(0x00C1);
  USB.productName("HORIPAD S");
  USB.manufacturerName("HORI CO.,LTD.");

  controller.begin();
  HID.begin();
  USB.begin();

  // UART from serial_bridge Arduino — same baud as Pro Micro version
  // GPIO 18 = RX1, GPIO 17 = TX1 (ESP32-S2 and S3)
  Serial1.begin(9600, SERIAL_8N1, 18, 17);

  // Wait for Switch to recognise the HID device, then announce ready
  delay(2000);
  controller.sendNeutral();
  Serial1.println("READY");
}

// ---------------------------------------------------------------------------
// Main loop — reads commands from serial_bridge Arduino over UART
// ---------------------------------------------------------------------------
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

        if (duration <= 0 || duration > 10000) duration = 100;

        if (isDpad(btnName)) {
          pressDpad(btnName, duration);
        } else {
          pressButton(btnName, duration);
        }

        Serial1.println("OK PRESS " + btnName);

      } else {
        Serial1.println("ERR unknown: " + inputBuffer);
      }

      inputBuffer = "";

    } else {
      inputBuffer += c;
      if (inputBuffer.length() > 64) inputBuffer = "";  // guard against garbage
    }
  }
}
