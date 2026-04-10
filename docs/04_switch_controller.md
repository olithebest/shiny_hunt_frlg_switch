# `src/controller/switch_controller.py` — Documentation

## Purpose

Sends button press commands to a Nintendo Switch. Two modes:

- **SERIAL mode** (production) — sends ASCII commands over USB serial to an
  Arduino Pro Micro flashed with `arduino/switch_controller/switch_controller.ino`.
  The Arduino appears to the Switch as a Nintendo Pro Controller via USB HID.
- **KEYBOARD mode** (testing only) — simulates keyboard presses via `pynput`.
  Does NOT control a real Switch; only useful for PC emulators.

---

## Hardware Setup (SERIAL mode)

```
PC  ──USB──►  Arduino UNO (serial_bridge.ino)
                  ↕ 3 jumper wires (TX/RX/GND)
             Arduino Pro Micro (switch_controller.ino)
                  ↕ USB
             Nintendo Switch dock
```

The **UNO** acts as a serial bridge between the PC and the Pro Micro.
The **Pro Micro** enumerates as a USB HID game controller on the Switch.

---

## Enums

### `ControllerMode`
```python
class ControllerMode(Enum):
    KEYBOARD = auto()
    SERIAL   = auto()
```

### `Button`
All Nintendo Switch buttons as enum values:
`A, B, X, Y, PLUS, MINUS, HOME, L, R, ZL, ZR, UP, DOWN, LEFT, RIGHT`

> `PLUS` = Start in GBA NSO
> `MINUS` = Select in GBA NSO

---

## `KEYBOARD_MAP`
Maps `Button` enum values to keyboard keys when running in KEYBOARD mode.
Uses `pynput` Key constants for special keys (arrow keys, Enter, Backspace).

---

## Class: `SwitchController`

### Constructor
```python
SwitchController(
    mode: ControllerMode = ControllerMode.KEYBOARD,
    port: str = "COM3",
    baud_rate: int = 9600,
)
```
- `mode` — KEYBOARD or SERIAL
- `port` — COM port of the Arduino UNO (Windows: `COM3`, `COM4`, etc.)
- `baud_rate` — must match the `Serial.begin()` value in both Arduino sketches (9600)

---

### `connect()`
Opens the connection:
- **SERIAL**: Opens `serial.Serial(port, baud_rate)`, waits 2 seconds for the
  Arduino to reset after DTR (Data Terminal Ready) toggles, then flushes the
  input buffer to discard garbage.
- **KEYBOARD**: Initializes `pynput.keyboard.Controller`.

---

### `disconnect()`
Closes the serial port if open.

---

### `press(button, hold_time=0.1, wait_after=0.1)`
Press and release a single button.

- `button` — a `Button` enum value
- `hold_time` — seconds to hold the button before releasing (default 100 ms)
- `wait_after` — seconds to wait after releasing (default 100 ms)

**Serial protocol:** Sends `PRESS {BUTTON_NAME} {hold_ms}\n` to the Arduino.
Example: `PRESS A 100\n`

**Keyboard fallback:** Uses `pynput` to press and release the mapped key.

---

### `soft_reset()`
Triggers a GBA-style soft reset: holds `ZL + ZR + PLUS + MINUS` simultaneously
for 300 ms. This combo is the NSO GBA "soft reset" shortcut.

**Serial protocol:** Sends `SOFT_RESET\n` to the Arduino, which presses all
four buttons at once.

---

### `_serial_press(button, hold_time)`
Internal method. Formats and sends the serial command. Protected by `self._lock`
(threading.Lock) to prevent concurrent command collisions.

### `_keyboard_press(button, hold_time)`
Internal method. Uses `pynput` to press the mapped key for `hold_time` seconds.

---

## Thread Safety

All button press operations are wrapped in `self._lock` (a `threading.Lock`).
This prevents the GUI thread and automation thread from sending commands
simultaneously, which would corrupt the serial byte stream.

---

## Serial Protocol Reference

Commands sent from PC to Arduino (ASCII, newline-terminated):

| Command | Effect |
|---------|--------|
| `PRESS A 100` | Press A for 100 ms |
| `PRESS UP 150` | Press D-pad Up for 150 ms |
| `SOFT_RESET` | Hold ZL+ZR+PLUS+MINUS for 300 ms |

The Arduino parses each line, actuates the HID buttons, and releases them
after the specified duration.
