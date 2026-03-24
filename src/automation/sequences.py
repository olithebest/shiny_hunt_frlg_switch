import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable, List

import numpy as np

from ..capture.capture_handler import CaptureHandler
from ..detection.shiny_detector import ShinyDetector, ShinyDetectionResult
from ..controller.switch_controller import SwitchController, Button
from .state_machine import AutomationState, StateMachine

logger = logging.getLogger(__name__)


@dataclass
class HuntResult:
    is_shiny:         bool
    encounters:       int
    frame:            Optional[np.ndarray]          = None
    detection_result: Optional[ShinyDetectionResult] = None


@dataclass
class HuntConfig:
    """
    Timing configuration (seconds) for a hunt sequence.
    All values can be tuned in config/settings.yaml or overridden per-target.
    """
    soft_reset_wait:          float = 5.0
    title_screen_wait:        float = 3.0
    continue_game_wait:       float = 6.0
    navigate_to_target_wait:  float = 1.0
    battle_start_wait:        float = 3.5
    sparkle_window_start:     float = 0.5
    sparkle_window_duration:  float = 2.0
    frames_per_second:        int   = 10


# Per-target timing overrides
_TARGET_CONFIGS = {
    "bulbasaur":  HuntConfig(navigate_to_target_wait=0.5),
    "charmander": HuntConfig(navigate_to_target_wait=0.5),
    "squirtle":   HuntConfig(navigate_to_target_wait=0.5),
    "lapras":     HuntConfig(navigate_to_target_wait=1.0),
    "eevee":      HuntConfig(navigate_to_target_wait=0.5),
    "zapdos":     HuntConfig(navigate_to_target_wait=1.5, battle_start_wait=4.0),
    "moltres":    HuntConfig(navigate_to_target_wait=1.5, battle_start_wait=4.0),
    "articuno":   HuntConfig(navigate_to_target_wait=1.5, battle_start_wait=4.0),
}

# Buttons to press (in order) after the save point is loaded.
# The user must save immediately before the target interaction.
_TARGET_INTERACTIONS = {
    "bulbasaur":  [Button.UP, Button.A],
    "charmander": [Button.UP, Button.A],
    "squirtle":   [Button.UP, Button.A],
    "lapras":     [Button.A],
    "eevee":      [Button.A],
    "zapdos":     [Button.A],
    "moltres":    [Button.A],
    "articuno":   [Button.A],
}

# How many D-pad RIGHT presses to reach the desired starter from the leftmost ball
_STARTER_POSITION = {
    "bulbasaur":  0,
    "charmander": 1,
    "squirtle":   2,
}


class HuntSequence:
    """
    Runs a full shiny hunt automation loop for a given target Pokemon.

    PRE-CONDITION (user must do this once before starting):
      Save the game at the position immediately before triggering the encounter:
        - Starters  : stand in front of the desired Poke Ball in Oak's lab
        - Lapras    : face the Silph Co. employee who gives Lapras
        - Eevee     : face the aide in Celadon Mansion who gives Eevee
        - Legendaries: stand one step away from the legendary Pokemon

    LOOP:
      1. Interact with target  →  2. Wait for battle  →  3. Capture sparkle window
      →  4. Analyze frames  →  5a. SHINY: stop & alert  |  5b. Soft reset & repeat
    """

    def __init__(
        self,
        target: str,
        controller: SwitchController,
        detector: ShinyDetector,
        capture: CaptureHandler,
        on_status: Optional[Callable[[str], None]] = None,
        on_encounter: Optional[Callable[[int, bool], None]] = None,
    ):
        self.target = target.lower()
        self.controller = controller
        self.detector = detector
        self.capture = capture
        self.on_status = on_status or (lambda msg: logger.info(msg))
        self.on_encounter = on_encounter or (lambda count, shiny: None)
        self.config = _TARGET_CONFIGS.get(self.target, HuntConfig())
        self.interactions = _TARGET_INTERACTIONS.get(self.target, [Button.A])
        self.state = StateMachine(AutomationState.IDLE)
        self._stop_event = threading.Event()
        self.encounters = 0

    def stop(self):
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str):
        logger.info(msg)
        self.on_status(msg)

    def _soft_reset_and_reload(self):
        self._log("Soft resetting...")
        self.state.transition(AutomationState.SOFT_RESETTING)
        self.controller.soft_reset()

        self._log(f"Waiting {self.config.soft_reset_wait}s for title screen...")
        self.state.transition(AutomationState.WAITING_FOR_RESET)
        time.sleep(self.config.soft_reset_wait)

        self._log("Pressing A on title screen...")
        self.state.transition(AutomationState.WAITING_FOR_TITLE)
        self.controller.press(Button.A)
        time.sleep(self.config.title_screen_wait)

        self._log("Selecting Continue...")
        self.controller.press(Button.A)
        time.sleep(self.config.continue_game_wait)

    def _interact_with_target(self):
        self._log(f"Interacting with {self.target.title()}...")
        self.state.transition(AutomationState.NAVIGATING_TO_TARGET)

        for button in self.interactions:
            self.controller.press(button, hold_time=0.15, wait_after=0.3)

        time.sleep(self.config.navigate_to_target_wait)

        if self.target in _STARTER_POSITION:
            self._navigate_starter_dialog()

    def _navigate_starter_dialog(self):
        """Press through Oak's dialog, navigate to the correct ball, confirm."""
        # Advance dialog until the starter selection screen
        for _ in range(5):
            self.controller.press(Button.A, hold_time=0.1, wait_after=0.4)

        # Move to the correct starter
        presses = _STARTER_POSITION.get(self.target, 0)
        for _ in range(presses):
            self.controller.press(Button.RIGHT, wait_after=0.3)

        # Confirm selection (A twice: pick + "Yes, this one!")
        self.controller.press(Button.A, wait_after=0.5)
        self.controller.press(Button.A, wait_after=0.5)

    def _capture_sparkle_window(self) -> List[np.ndarray]:
        self._log("Waiting for battle to start...")
        self.state.transition(AutomationState.WAITING_FOR_BATTLE)
        time.sleep(self.config.battle_start_wait)

        self._log("Capturing sparkle window...")
        self.state.transition(AutomationState.CHECKING_FOR_SHINY)
        time.sleep(self.config.sparkle_window_start)

        frames: List[np.ndarray] = []
        interval = 1.0 / max(self.config.frames_per_second, 1)
        end_time = time.time() + self.config.sparkle_window_duration

        while time.time() < end_time and not self._stop_event.is_set():
            frame = self.capture.grab_frame()
            if frame is not None:
                frames.append(frame)
            time.sleep(interval)

        return frames

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_cycle(self) -> HuntResult:
        """Run one complete hunt cycle (interact → detect → reset if needed)."""
        if self._stop_event.is_set():
            return HuntResult(is_shiny=False, encounters=self.encounters)

        self._interact_with_target()

        if self._stop_event.is_set():
            return HuntResult(is_shiny=False, encounters=self.encounters)

        frames = self._capture_sparkle_window()
        detection = self.detector.check_window(frames)
        self.encounters += 1
        self.on_encounter(self.encounters, detection.is_shiny)

        if detection.is_shiny:
            self._log(f"🌟 SHINY {self.target.upper()} after {self.encounters} encounters!")
            self.state.transition(AutomationState.SHINY_FOUND)
            return HuntResult(
                is_shiny=True,
                encounters=self.encounters,
                frame=detection.frame,
                detection_result=detection,
            )

        self._log(f"#{self.encounters}: Not shiny (confidence {detection.confidence:.2f}). Resetting...")
        self._soft_reset_and_reload()

        return HuntResult(
            is_shiny=False,
            encounters=self.encounters,
            frame=detection.frame,
            detection_result=detection,
        )

    def run(self) -> HuntResult:
        """Run the full hunt loop until a shiny is found or stop() is called."""
        self._stop_event.clear()
        self._log(f"Starting shiny hunt for {self.target.title()}. Good luck!")

        # Load from save the first time
        self._soft_reset_and_reload()

        while not self._stop_event.is_set():
            result = self.run_cycle()
            if result.is_shiny or self._stop_event.is_set():
                self.state.transition(AutomationState.STOPPED)
                return result

        self.state.transition(AutomationState.STOPPED)
        return HuntResult(is_shiny=False, encounters=self.encounters)
