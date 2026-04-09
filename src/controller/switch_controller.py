import time
import threading
import logging
from enum import Enum, auto
from typing import Optional

try:
    from pynput.keyboard import Controller as KeyboardController, Key
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

logger = logging.getLogger(__name__)


class ControllerMode(Enum):
    KEYBOARD = auto()   # Simulates keypresses — useful for PC emulator testing only
    SERIAL   = auto()   # Sends commands to Arduino Leonardo/Pro Micro via serial port


class Button(Enum):
    """Nintendo Switch button identifiers."""
    A      = "A"
    B      = "B"
    X      = "X"
    Y      = "Y"
    PLUS   = "PLUS"    # Maps to Start  in GBA NSO
    MINUS  = "MINUS"   # Maps to Select in GBA NSO
    HOME   = "HOME"
    L      = "L"
    R      = "R"
    ZL     = "ZL"
    ZR     = "ZR"
    UP     = "UP"
    DOWN   = "DOWN"
    LEFT   = "LEFT"
    RIGHT  = "RIGHT"


# Keyboard fallback map — only useful when testing with a PC emulator
KEYBOARD_MAP = {
    Button.A:     "z",
    Button.B:     "x",
    Button.X:     "a",
    Button.Y:     "s",
    Button.PLUS:  "enter" if not PYNPUT_AVAILABLE else Key.enter,
    Button.MINUS: "backspace" if not PYNPUT_AVAILABLE else Key.backspace,
    Button.L:     "q",
    Button.R:     "w",
    Button.ZL:    "e",
    Button.ZR:    "r",
    Button.UP:    "up" if not PYNPUT_AVAILABLE else Key.up,
    Button.DOWN:  "down" if not PYNPUT_AVAILABLE else Key.down,
    Button.LEFT:  "left" if not PYNPUT_AVAILABLE else Key.left,
    Button.RIGHT: "right" if not PYNPUT_AVAILABLE else Key.right,
}


class SwitchController:
    """
    Sends button inputs to the Nintendo Switch.

    KEYBOARD mode  — simulates keyboard keypresses (testing only, does NOT
                     control a real Switch).

    SERIAL mode    — sends ASCII commands over serial to an Arduino Leonardo
                     or Pro Micro flashed with the companion sketch located at
                     arduino/switch_controller/switch_controller.ino.
                     The Arduino enumerates as a Nintendo Switch Pro Controller
                     via USB HID, so the Switch sees it as a real controller.

    Serial protocol (newline-terminated):
        PRESS A 100      → press A for 100 ms
        SOFT_RESET       → hold ZL+ZR+PLUS+MINUS for 300 ms (GBA soft reset)
    """

    def __init__(
        self,
        mode: ControllerMode = ControllerMode.KEYBOARD,
        port: str = "COM3",
        baud_rate: int = 9600,
    ):
        self.mode = mode
        self.port = port
        self.baud_rate = baud_rate
        self._serial: Optional["serial.Serial"] = None
        self._keyboard: Optional[KeyboardController] = None
        self._lock = threading.Lock()

    def connect(self):
        if self.mode == ControllerMode.SERIAL:
            if not SERIAL_AVAILABLE:
                raise RuntimeError("pyserial not installed. Run: pip install pyserial")
            self._serial = serial.Serial(self.port, self.baud_rate, timeout=1)
            time.sleep(2)  # Give Arduino time to reset after serial connection
            self._serial.reset_input_buffer()  # Discard garbage from Arduino DTR reset
            logger.info(f"Serial controller connected on {self.port}")
        elif self.mode == ControllerMode.KEYBOARD:
            if not PYNPUT_AVAILABLE:
                raise RuntimeError("pynput not installed. Run: pip install pynput")
            self._keyboard = KeyboardController()
            logger.info("Keyboard controller ready (test mode)")

    def disconnect(self):
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def press(self, button: Button, hold_time: float = 0.1, wait_after: float = 0.1):
        """Press and release a single button."""
        with self._lock:
            if self.mode == ControllerMode.SERIAL:
                self._serial_press(button, hold_time)
            elif self.mode == ControllerMode.KEYBOARD:
                self._keyboard_press(button, hold_time)
        time.sleep(wait_after)

    def _serial_press(self, button: Button, hold_time: float):
        if self._serial and self._serial.is_open:
            cmd = f"PRESS {button.value} {int(hold_time * 1000)}\n".encode()
            self._serial.write(cmd)
            self._serial.flush()

    def _keyboard_press(self, button: Button, hold_time: float):
        key = KEYBOARD_MAP.get(button)
        if key and self._keyboard:
            self._keyboard.press(key)
            time.sleep(hold_time)
            self._keyboard.release(key)

    def soft_reset(self):
        """
        GBA soft reset: ZL + ZR + PLUS + MINUS held simultaneously.
        This is the NSO GBA equivalent of the original L + R + Start + Select.
        """
        with self._lock:
            if self.mode == ControllerMode.SERIAL:
                if self._serial and self._serial.is_open:
                    self._serial.write(b"SOFT_RESET\n")
                    self._serial.flush()
            elif self.mode == ControllerMode.KEYBOARD and self._keyboard:
                keys = [
                    KEYBOARD_MAP[Button.ZL],
                    KEYBOARD_MAP[Button.ZR],
                    KEYBOARD_MAP[Button.PLUS],
                    KEYBOARD_MAP[Button.MINUS],
                ]
                for k in keys:
                    self._keyboard.press(k)
                time.sleep(0.3)
                for k in keys:
                    self._keyboard.release(k)
        time.sleep(0.5)

    def wait(self, seconds: float):
        time.sleep(seconds)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
