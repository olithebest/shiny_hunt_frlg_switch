import time
import random
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

    Reset sequence steps (after soft-reset from inside the game):
      1. Copyright screen appears  →  wait intro_wait seconds
      2. Press A to skip intro animation  →  "PRESS START" title appears
      3. Wait title_appear_wait seconds
      4. Press A on title screen  →  main menu (CONTINUE / NEW GAME)
      5. Wait menu_wait seconds
      6. Press A to select CONTINUE  →  memories screen appears
      7. Press B x memories_b_presses to skip "Previously on your quest..."
      8. Wait world_load_wait seconds  →  overworld fully loaded, ready
    """
    # Step 1: wait after soft-reset before pressing A to skip intro
    intro_wait:              float = 3.5
    # Step 3: wait after skipping intro before title screen is ready
    title_appear_wait:       float = 1.5
    # Step 5: wait after pressing A on title screen before menu is ready
    menu_wait:               float = 1.0
    # Step 7: B presses + interval to dismiss memories
    memories_b_presses:      int   = 6
    memories_b_interval:     float = 0.4
    # Step 8: wait after memories dismissed before overworld is controllable
    world_load_wait:         float = 2.0
    # After pressing A on target: wait before battle starts
    navigate_to_target_wait: float = 1.0
    # Legendaries only: wait for cry to finish, then press A to enter battle.
    # 0.0 = no cry press (starters, Lapras, Eevee go straight into battle on first A)
    cry_wait:                float = 0.0
    battle_start_wait:       float = 3.5
    sparkle_window_start:    float = 0.5
    sparkle_window_duration: float = 2.0
    frames_per_second:       int   = 10


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
    # Mewtwo: save one step in front of it in Cerulean Cave B2F.
    # Longer battle_start_wait because Mewtwo has a longer intro fanfare.
    # Extra memories_b_presses because the memories screen can be multi-page.
    "mewtwo":     HuntConfig(
        intro_wait=3.5,
        title_appear_wait=2.0,
        menu_wait=3.0,
        memories_b_presses=8,
        memories_b_interval=0.4,
        world_load_wait=2.0,
        navigate_to_target_wait=0.5,
        cry_wait=2.5,        # wait for Mewtwo's cry to finish, then press A to enter battle
        battle_start_wait=5.0,
        sparkle_window_start=0.3,
        sparkle_window_duration=2.5,
    ),
    # Ho-Oh: Switch 2 FRLG event. Save on the stairs, walk UP one step to
    # trigger the cutscene. Ho-Oh flies in from above, stops near the player,
    # and the battle starts AUTOMATICALLY — no A press needed.
    # cry_wait=0 because there's no "press A to enter battle" moment.
    # navigate_to_target_wait covers the entire fly-in cutscene.
    "ho-oh":      HuntConfig(
        intro_wait=3.5,
        title_appear_wait=2.0,
        menu_wait=3.0,
        memories_b_presses=8,
        memories_b_interval=0.4,
        world_load_wait=2.0,
        navigate_to_target_wait=6.0,  # fly-in cutscene (~5-6s)
        cry_wait=0.0,                 # battle starts automatically
        battle_start_wait=5.0,
        sparkle_window_start=0.3,
        sparkle_window_duration=2.5,
    ),
    # Lugia: Switch 2 FRLG event. Static encounter, save one step in front.
    "lugia":      HuntConfig(
        intro_wait=3.5,
        title_appear_wait=2.0,
        menu_wait=3.0,
        memories_b_presses=8,
        memories_b_interval=0.4,
        world_load_wait=2.0,
        navigate_to_target_wait=0.5,
        cry_wait=2.5,
        battle_start_wait=5.0,
        sparkle_window_start=0.3,
        sparkle_window_duration=2.5,
    ),
    # Deoxys: Switch 2 FRLG event. Static encounter, save one step in front.
    "deoxys":     HuntConfig(
        intro_wait=3.5,
        title_appear_wait=2.0,
        menu_wait=3.0,
        memories_b_presses=8,
        memories_b_interval=0.4,
        world_load_wait=2.0,
        navigate_to_target_wait=0.5,
        cry_wait=2.0,
        battle_start_wait=5.0,
        sparkle_window_start=0.3,
        sparkle_window_duration=2.5,
    ),
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
    "mewtwo":     [Button.A],
    "ho-oh":      [Button.UP],   # walk UP triggers fly-in cutscene → auto battle
    "lugia":      [Button.A],
    "deoxys":     [Button.A],
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
        on_progress: Optional[Callable[[str, int], None]] = None,
        start_encounters: int = 0,
    ):
        self.target = target.lower()
        self.controller = controller
        self.detector = detector
        self.capture = capture
        self.on_status = on_status or (lambda msg: logger.info(msg))
        self.on_encounter = on_encounter or (lambda count, shiny: None)
        self.on_progress = on_progress or (lambda target, count: None)
        self.config = _TARGET_CONFIGS.get(self.target, HuntConfig())
        self.interactions = _TARGET_INTERACTIONS.get(self.target, [Button.A])
        self.state = StateMachine(AutomationState.IDLE)
        self._stop_event = threading.Event()
        self.encounters = start_encounters

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

        # Step 1: wait for copyright screen to pass and intro animation to begin
        self._log(f"Waiting {self.config.intro_wait}s for intro animation...")
        self.state.transition(AutomationState.WAITING_FOR_RESET)
        time.sleep(self.config.intro_wait)

        # Step 2a: press A to skip the Nidorino/Gengar battle intro
        self._log("Skipping intro animation - press 1 (A)...")
        self.controller.press(Button.A, hold_time=0.1, wait_after=0.5)

        # Step 2b: press A again to skip the star/shooting-star animation
        self._log("Skipping intro animation - press 2 (A)...")
        self.controller.press(Button.A, hold_time=0.1, wait_after=0.5)

        # Now the Venusaur "PRESS START" title screen is showing
        self._log(f"Waiting {self.config.title_appear_wait}s for title screen...")
        time.sleep(self.config.title_appear_wait)

        # Random jitter BEFORE pressing START — this is the key moment that determines
        # the RNG seed. Without variance here, every reset hits the exact same seed
        # and you'd loop through the same non-shiny frame forever.
        jitter_start = random.uniform(0.0, 0.5)
        self._log(f"RNG jitter: +{jitter_start*1000:.0f}ms before START")
        time.sleep(jitter_start)

        # Step 3: press A (acts as START) on the title screen → CONTINUE / NEW GAME menu
        self._log("Pressing START on title screen...")
        self.state.transition(AutomationState.WAITING_FOR_TITLE)
        self.controller.press(Button.A)
        time.sleep(self.config.menu_wait)

        # Random jitter BEFORE pressing CONTINUE — a second variance point for extra seed coverage
        jitter_continue = random.uniform(0.0, 0.3)
        self._log(f"RNG jitter: +{jitter_continue*1000:.0f}ms before CONTINUE")
        time.sleep(jitter_continue)

        # Step 6: press A to select CONTINUE from main menu
        self._log("Selecting Continue...")
        self.controller.press(Button.A)
        time.sleep(2.0)  # wait for memories screen to appear

        # Step 7: press B repeatedly to skip "Previously on your quest..." memories
        self._log(f"Skipping memories ({self.config.memories_b_presses}x B)...")
        for _ in range(self.config.memories_b_presses):
            self.controller.press(Button.B, hold_time=0.1, wait_after=self.config.memories_b_interval)

        # Step 8: wait for overworld to fully load
        self._log(f"Waiting {self.config.world_load_wait}s for world to load...")
        time.sleep(self.config.world_load_wait)

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
        # For legendaries: first A triggered the cry — wait for it, then press A to enter battle
        if self.config.cry_wait > 0:
            self._log(f"Waiting {self.config.cry_wait}s for cry to finish...")
            time.sleep(self.config.cry_wait)
            self._log("Pressing A to enter battle...")
            self.controller.press(Button.A)

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
        detection = self.detector.check_window(frames, target=self.target, encounter=self.encounters + 1)
        self.encounters += 1
        self.on_encounter(self.encounters, detection.is_shiny)
        self.on_progress(self.target, self.encounters)

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


class RNGHuntSequence:
    """
    RNG manipulation hunt: uses precise timing (no random jitter) to hit a
    specific PRNG frame that produces a shiny PID.

    Instead of random jitter + visual detection over thousands of resets,
    this targets a known shiny frame by controlling the exact millisecond
    delay before pressing START.  It still uses shiny detection to CONFIRM
    the hit, and sweeps nearby frames (±spread) if the first attempt misses.

    PRE-CONDITION:
      Same as HuntSequence — save immediately before the encounter.
      You must know your TID + SID (use find_sid.py) and have a target frame
      (use find_shiny_frame.py).
    """

    def __init__(
        self,
        target: str,
        controller: SwitchController,
        detector: ShinyDetector,
        capture: CaptureHandler,
        start_ms: int,
        continue_ms: int = 0,
        spread_ms: int = 96,
        step_ms: int = 16,
        on_status: Optional[Callable[[str], None]] = None,
        on_encounter: Optional[Callable[[int, bool], None]] = None,
        on_progress: Optional[Callable[[str, int], None]] = None,
        start_encounters: int = 0,
    ):
        self.target = target.lower()
        self.controller = controller
        self.detector = detector
        self.capture = capture
        self.start_ms = start_ms
        self.continue_ms = continue_ms
        self.spread_ms = spread_ms
        self.step_ms = step_ms
        self.on_status = on_status or (lambda msg: logger.info(msg))
        self.on_encounter = on_encounter or (lambda count, shiny: None)
        self.on_progress = on_progress or (lambda target, count: None)
        self.config = _TARGET_CONFIGS.get(self.target, HuntConfig())
        self.interactions = _TARGET_INTERACTIONS.get(self.target, [Button.A])
        self.state = StateMachine(AutomationState.IDLE)
        self._stop_event = threading.Event()
        self.encounters = start_encounters

    def stop(self):
        self._stop_event.set()

    def _log(self, msg: str):
        logger.info(msg)
        self.on_status(msg)

    def _build_timing_schedule(self) -> list[tuple[int, int]]:
        """Build list of (start_ms, continue_ms) to try, center-out."""
        half = self.spread_ms // 2
        start_values = list(range(
            max(0, self.start_ms - half),
            self.start_ms + half + 1,
            self.step_ms,
        ))
        # Sort center-out so we try the target frame first
        start_values.sort(key=lambda x: abs(x - self.start_ms))

        schedule = [(s, self.continue_ms) for s in start_values]
        return schedule

    def _run_one_attempt(self, start_ms: int, continue_ms: int) -> HuntResult:
        """Run one reset cycle with exact timing, return result.

        start_ms is the total time from soft-reset to pressing START on the
        title screen.  This matches the timing shown by ten-lines / PokeFinder
        — measured from the moment the PRNG resets to seed 0.

        The intro is skipped with fast A presses, but the START press is timed
        precisely against the reset moment (not relative to when the title
        screen appears).
        """
        self._log(f"RNG attempt: START at T={start_ms}ms from reset")
        self.state.transition(AutomationState.SOFT_RESETTING)

        # Record the exact moment of soft reset — PRNG resets to seed 0 here
        self.controller.soft_reset()
        t_reset = time.perf_counter()

        # Skip intro as fast as possible (doesn't affect PRNG advancement)
        self.state.transition(AutomationState.WAITING_FOR_RESET)
        time.sleep(self.config.intro_wait)
        self.controller.press(Button.A, hold_time=0.1, wait_after=0.5)
        self.controller.press(Button.A, hold_time=0.1, wait_after=0.5)

        # Wait until the precise target time from reset, then press START
        elapsed_ms = (time.perf_counter() - t_reset) * 1000
        remaining_ms = start_ms - elapsed_ms
        if remaining_ms > 0:
            self._log(f"  Waiting {remaining_ms:.0f}ms more for precise START timing...")
            time.sleep(remaining_ms / 1000.0)
        else:
            self._log(f"  ⚠ Already past target by {-remaining_ms:.0f}ms (intro took too long)")

        self.state.transition(AutomationState.WAITING_FOR_TITLE)
        actual_ms = (time.perf_counter() - t_reset) * 1000
        self.controller.press(Button.A)
        self._log(f"  START pressed at T={actual_ms:.0f}ms (target was {start_ms}ms, delta={actual_ms-start_ms:+.0f}ms)")
        time.sleep(self.config.menu_wait)

        # Fixed CONTINUE jitter
        time.sleep(continue_ms / 1000.0)
        self.controller.press(Button.A)
        time.sleep(2.0)

        # Skip memories
        for _ in range(self.config.memories_b_presses):
            self.controller.press(Button.B, hold_time=0.1, wait_after=self.config.memories_b_interval)
        time.sleep(self.config.world_load_wait)

        # Interact
        self.state.transition(AutomationState.NAVIGATING_TO_TARGET)
        for button in self.interactions:
            self.controller.press(button, hold_time=0.15, wait_after=0.3)
        time.sleep(self.config.navigate_to_target_wait)

        # Capture sparkle window
        if self.config.cry_wait > 0:
            time.sleep(self.config.cry_wait)
            self.controller.press(Button.A)

        self.state.transition(AutomationState.WAITING_FOR_BATTLE)
        time.sleep(self.config.battle_start_wait)

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

        detection = self.detector.check_window(
            frames, target=self.target, encounter=self.encounters + 1
        )
        self.encounters += 1
        self.on_encounter(self.encounters, detection.is_shiny)
        self.on_progress(self.target, self.encounters)

        return HuntResult(
            is_shiny=detection.is_shiny,
            encounters=self.encounters,
            frame=detection.frame,
            detection_result=detection,
        )

    def run(self) -> HuntResult:
        """
        Run RNG manipulation: try the target frame first, then sweep nearby
        frames until a shiny is found or all attempts exhausted.
        """
        self._stop_event.clear()
        schedule = self._build_timing_schedule()
        total = len(schedule)

        self._log(
            f"Starting RNG hunt for {self.target.title()} — "
            f"target START=+{self.start_ms}ms, sweeping ±{self.spread_ms//2}ms "
            f"({total} attempts)"
        )

        for i, (s_ms, c_ms) in enumerate(schedule):
            if self._stop_event.is_set():
                break

            self._log(f"Attempt {i+1}/{total}")
            result = self._run_one_attempt(s_ms, c_ms)

            if result.is_shiny:
                self._log(
                    f"🌟 SHINY {self.target.upper()} found! "
                    f"START=+{s_ms}ms, attempt {i+1}/{total}"
                )
                self.state.transition(AutomationState.SHINY_FOUND)
                return result

            self._log(f"Attempt {i+1}/{total}: not shiny at START=+{s_ms}ms")

        self._log(f"RNG sweep complete — {total} attempts, no shiny found.")
        self._log("Try adjusting --base-offset in find_shiny_frame.py or increasing --spread.")
        self.state.transition(AutomationState.STOPPED)
        return HuntResult(is_shiny=False, encounters=self.encounters)
