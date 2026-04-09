"""
Replay Seed Tool
================
Replays a specific RNG seed by using fixed jitter values instead of random ones.
Use this to recover a shiny that was missed due to a detection failure.

Encounter 10404 (shiny Mewtwo) used:
  START jitter:    +402ms
  CONTINUE jitter: +221ms

Usage:
    C:\\Python310\\python.exe tools/replay_seed.py --start-ms 402 --continue-ms 221

The script does ONE full reset + encounter cycle using those exact delays,
then STOPS and waits — it will NOT soft-reset again, giving you time to catch it.

PRE-CONDITIONS:
  1. OBS Virtual Camera running (Switch scene active)
  2. Sender Arduino (COM7) plugged in
  3. Game is currently at a state where a soft reset will work
     (i.e. you're in the overworld or at the title screen)
  4. Your save is immediately before Mewtwo (one step away in Cerulean Cave B2F)
"""

import sys
import os
import argparse
import logging
import time
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.capture.capture_handler import CaptureHandler
from src.controller.switch_controller import SwitchController, ControllerMode
from src.detection.shiny_detector import ShinyDetector
from src.automation.sequences import HuntConfig, _TARGET_CONFIGS
from src.controller.switch_controller import Button
from src.automation.state_machine import StateMachine, AutomationState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_settings(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Replay a specific RNG seed for shiny recovery")
    parser.add_argument("--start-ms",    type=int, required=True,
                        help="Jitter ms used before START press (e.g. 402)")
    parser.add_argument("--continue-ms", type=int, required=True,
                        help="Jitter ms used before CONTINUE press (e.g. 221)")
    parser.add_argument("--target",      default="mewtwo",
                        help="Pokemon target (default: mewtwo)")
    parser.add_argument("--skip-reset",  action="store_true",
                        help="Skip the soft reset — use if already on title screen")
    args = parser.parse_args()

    cfg = load_settings()

    print()
    print("=" * 60)
    print("  REPLAY SEED — Shiny Recovery")
    print("=" * 60)
    print(f"  Target:          {args.target.title()}")
    print(f"  START jitter:    +{args.start_ms}ms")
    print(f"  CONTINUE jitter: +{args.continue_ms}ms")
    print()
    print("  This will perform ONE reset cycle using those exact delays.")
    print("  If the shiny appears, the bot will STOP and wait — do NOT")
    print("  press anything on your PC until you've caught it in-game!")
    print()
    input("  Press ENTER to start...")

    # Open capture
    device_idx = cfg["capture"]["device_index"]
    capture = CaptureHandler(device_index=device_idx)
    capture.open()
    time.sleep(1)
    test_frame = capture.grab_frame()
    if test_frame is None:
        log.error("No frame from camera. Is OBS Virtual Camera running?")
        sys.exit(1)
    log.info(f"Camera OK — {test_frame.shape[1]}x{test_frame.shape[0]}")

    # Open controller
    port     = cfg["controller"]["serial_port"]
    baud     = cfg["controller"]["baud_rate"]
    controller = SwitchController(mode=ControllerMode.SERIAL, port=port, baud_rate=baud)
    controller.connect()
    log.info(f"Controller connected on {port}")

    config = _TARGET_CONFIGS.get(args.target, HuntConfig())
    detector = ShinyDetector()

    try:
        # ── SOFT RESET ────────────────────────────────────────────────
        if not args.skip_reset:
            log.info("Soft resetting...")
            controller.soft_reset()
            log.info(f"Waiting {config.intro_wait}s for intro animation...")
            time.sleep(config.intro_wait)

            log.info("Skipping intro animation - press 1 (A)...")
            controller.press(Button.A, hold_time=0.1, wait_after=0.5)
            log.info("Skipping intro animation - press 2 (A)...")
            controller.press(Button.A, hold_time=0.1, wait_after=0.5)

            log.info(f"Waiting {config.title_appear_wait}s for title screen...")
            time.sleep(config.title_appear_wait)
        else:
            log.info("Skipping soft reset (--skip-reset flag set).")

        # ── FIXED JITTER — START ──────────────────────────────────────
        jitter_start = args.start_ms / 1000.0
        log.info(f"Fixed RNG jitter: +{args.start_ms}ms before START")
        time.sleep(jitter_start)

        log.info("Pressing START on title screen...")
        controller.press(Button.A)
        time.sleep(config.menu_wait)

        # ── FIXED JITTER — CONTINUE ───────────────────────────────────
        jitter_continue = args.continue_ms / 1000.0
        log.info(f"Fixed RNG jitter: +{args.continue_ms}ms before CONTINUE")
        time.sleep(jitter_continue)

        log.info("Selecting Continue...")
        controller.press(Button.A)
        time.sleep(2.0)

        # ── SKIP MEMORIES ─────────────────────────────────────────────
        log.info(f"Skipping memories ({config.memories_b_presses}x B)...")
        for _ in range(config.memories_b_presses):
            controller.press(Button.B, hold_time=0.1, wait_after=config.memories_b_interval)

        log.info(f"Waiting {config.world_load_wait}s for world to load...")
        time.sleep(config.world_load_wait)

        # ── INTERACT WITH TARGET ──────────────────────────────────────
        log.info(f"Interacting with {args.target.title()}...")
        controller.press(Button.A, hold_time=0.15, wait_after=0.3)
        time.sleep(config.navigate_to_target_wait)

        # ── CAPTURE SPARKLE WINDOW ────────────────────────────────────
        if config.cry_wait > 0:
            log.info(f"Waiting {config.cry_wait}s for cry to finish...")
            time.sleep(config.cry_wait)
            log.info("Pressing A to enter battle...")
            controller.press(Button.A)

        log.info("Waiting for battle to start...")
        time.sleep(config.battle_start_wait)
        log.info("Capturing sparkle window...")
        time.sleep(config.sparkle_window_start)

        frames = []
        interval = 1.0 / max(10, 1)
        end_time = time.time() + config.sparkle_window_duration
        while time.time() < end_time:
            frame = capture.grab_frame()
            if frame is not None:
                frames.append(frame)
            time.sleep(interval)

        # ── DETECT ────────────────────────────────────────────────────
        result = detector.check_window(frames, target=args.target, encounter=99999)

        print()
        print("=" * 60)
        if result.is_shiny:
            print("  *** SHINY DETECTED! ***")
            print(f"  Target: {args.target.title()}")
            print()
            print("  DO NOT RESTART! Catch it now in-game!")
            print("  The bot has stopped — you're in control.")
            print("=" * 60)
            log.info(f"SHINY {args.target.upper()} CONFIRMED — replay successful!")
        else:
            print("  Result: NOT shiny")
            print()
            print("  The seed didn't produce a shiny this run.")
            print("  Possible causes:")
            print("  • System timer resolution caused slight drift from the target ms")
            print("  • The game sequence took slightly different real-world time")
            print("  • Try running again — timing can vary ±1 frame (±16ms)")
            print("=" * 60)

    finally:
        capture.close()
        controller.disconnect()


if __name__ == "__main__":
    main()
