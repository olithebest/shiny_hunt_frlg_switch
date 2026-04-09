/*
 * Pro Micro LED Test
 * ------------------
 * The Pro Micro has two built-in LEDs:
 *   - RX LED on pin 17 (active LOW — write LOW to turn ON)
 *   - TX LED on pin 30 (active LOW)
 * The standard Blink example (pin 13) does NOT blink on Pro Micro.
 */

#define RX_LED 17
#define TX_LED 30

void setup() {
  pinMode(RX_LED, OUTPUT);
  pinMode(TX_LED, OUTPUT);
}

void loop() {
  // Both LEDs ON
  digitalWrite(RX_LED, LOW);
  digitalWrite(TX_LED, LOW);
  delay(500);

  // Both LEDs OFF
  digitalWrite(RX_LED, HIGH);
  digitalWrite(TX_LED, HIGH);
  delay(500);
}
