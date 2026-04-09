/*
NEW SKETCH

 * Switch 2 Controller Test
 * ------------------------
 * Presses A every 3 seconds to verify the Switch recognizes the controller.
 *
 * HOW TO USE:
 * 1. Upload this sketch with Arduino connected to PC
 * 2. Unplug Arduino from PC
 * 3. Plug Arduino into Switch 2 dock USB port
 * 4. Go to Switch Home screen
 * 5. Wait ~5 seconds — you should see A being pressed (cursor moves / dialog opens)
 */

#include <NintendoSwitchControlLibrary.h>

void setup() {
  // Press L several times — this is the standard way to get the Switch
  // to recognize a newly connected wired controller
  pushButton(Button::L, 500, 5);
}

void loop() {
  // Press A for 200ms, then wait 3 seconds, repeat
  pushButton(Button::A, 3000);
}
