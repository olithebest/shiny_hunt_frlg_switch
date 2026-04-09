"""
Shiny Hunt Runner
=================
Starts the automated shiny hunt loop.

PRE-CONDITIONS (do these before running):
  1. OBS Studio is open with the SWITCH2 scene active and Virtual Camera started
  2. The Sender Arduino (COM7) is plugged into your PC via USB
  3. The Pro Micro is plugged into the Switch dock USB port
  4. The Switch is docked and running FRLG via NSO
  5. You have saved the game IMMEDIATELY before the Mewtwo encounter
     (standing one step away from the Poke Ball in Cerulean Cave B2F)

Usage:
    cd C:\\Users\\olivi\\Desktop\\coding_projects\\shiny_hunt_frlg_switch
    C:\\Python310\\python.exe tools/run_hunt.py
    C:\\Python310\\python.exe tools/run_hunt.py --target mewtwo   (default)
    C:\\Python310\\python.exe tools/run_hunt.py --dry-run          (no Arduino needed)
"""

import sys
import os
import argparse
import logging
import time
import ctypes

# Make sure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import yaml
import cv2

from src.capture.capture_handler import CaptureHandler
from src.controller.switch_controller import SwitchController, ControllerMode
from src.detection.shiny_detector import ShinyDetector
from src.automation.sequences import HuntSequence, RNGHuntSequence

_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "hunt.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.normpath(_LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Keep the system awake (prevent sleep) but allow the screen to turn off.
# ES_CONTINUOUS | ES_SYSTEM_REQUIRED — no ES_DISPLAY_REQUIRED so monitor can sleep.
_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001
ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)


def load_settings(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


_PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "hunt_progress.json")


def load_progress(target: str) -> int:
    """Return the saved encounter count for this target (0 if none)."""
    path = os.path.normpath(_PROGRESS_FILE)
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = json.load(f)
            return int(data.get(target, 0))
        except (json.JSONDecodeError, ValueError):
            pass
    return 0


def save_progress(target: str, count: int):
    """Persist the encounter count for this target."""
    path = os.path.normpath(_PROGRESS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {}
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    data[target] = count
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def max_encounter_on_disk(target: str) -> int:
    """Scan the encounters folder and return the highest encounter number
    already saved for *target*.  Returns 0 if no files exist."""
    enc_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "screenshots", "encounters")
    )
    if not os.path.isdir(enc_dir):
        return 0
    import re
    pattern = re.compile(rf"^{re.escape(target)}_(\d+)_full\.png$")
    highest = 0
    for name in os.listdir(enc_dir):
        m = pattern.match(name)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


def on_status(msg: str):
    print(f"  >> {msg}")


def on_encounter(count: int, is_shiny: bool):
    tag = "  *** SHINY! ***" if is_shiny else ""
    print(f"  Encounter #{count}{tag}")


VALID_TARGETS = [
    "mewtwo", "zapdos", "articuno", "moltres",
    "ho-oh", "lugia", "deoxys",
    "bulbasaur", "charmander", "squirtle",
    "lapras", "eevee",
]


def main():
    parser = argparse.ArgumentParser(description="Shiny Hunt Automation")
    parser.add_argument("--target", default=None,
                        help="Pokemon to hunt (e.g. mewtwo, ho-oh, lugia, deoxys)")
    parser.add_argument("--mode", choices=["reset", "rng"], default="reset",
                        help="Hunt mode: 'reset' = brute-force resets (default), "
                             "'rng' = RNG manipulation (requires --start-ms)")
    parser.add_argument("--start-ms", type=int, default=None,
                        help="[RNG mode] Total ms from soft-reset to START press (from ten-lines / find_shiny_frame.py)")
    parser.add_argument("--continue-ms", type=int, default=0,
                        help="[RNG mode] CONTINUE jitter in ms (default: 0)")
    parser.add_argument("--spread", type=int, default=96,
                        help="[RNG mode] Sweep ±spread/2 ms around target (default: 96)")
    parser.add_argument("--step", type=int, default=16,
                        help="[RNG mode] Step size in ms (default: 16 = ~1 GBA frame)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Arduino — only test capture + detection, no button presses")
    args = parser.parse_args()

    # ── Target selection ───────────────────────────────────────────────
    if args.target is None:
        print("\n" + "=" * 50)
        print("  SHINY HUNT — Target Selection")
        print("=" * 50)
        print()
        print("  Legendaries:")
        print("    1. Mewtwo        (Cerulean Cave)")
        print("    2. Zapdos        (Power Plant)")
        print("    3. Articuno      (Seafoam Islands)")
        print("    4. Moltres       (Mt. Ember)")
        print()
        print("  Switch 2 Events:")
        print("    5. Ho-Oh")
        print("    6. Lugia")
        print("    7. Deoxys")
        print()
        print("  Starters:")
        print("    8. Bulbasaur")
        print("    9. Charmander")
        print("   10. Squirtle")
        print()
        print("  Gift Pokemon:")
        print("   11. Lapras        (Silph Co.)")
        print("   12. Eevee         (Celadon Mansion)")
        print()

        choice = input("  Enter number (1-12): ").strip()
        target_map = {
            "1": "mewtwo", "2": "zapdos", "3": "articuno", "4": "moltres",
            "5": "ho-oh", "6": "lugia", "7": "deoxys",
            "8": "bulbasaur", "9": "charmander", "10": "squirtle",
            "11": "lapras", "12": "eevee",
        }
        args.target = target_map.get(choice)
        if not args.target:
            print(f"  Invalid choice: {choice}")
            sys.exit(1)
        print(f"\n  Selected: {args.target.upper()}")

        # Ask for mode if not specified via CLI
        if args.mode == "reset":
            print()
            print("  Hunt mode:")
            print("    1. Reset Hunt   (brute-force resets with shiny detection)")
            print("    2. RNG Hunt     (precise timing from TID/SID — much faster)")
            mode_choice = input("  Enter 1 or 2 [default: 1]: ").strip()
            if mode_choice == "2":
                args.mode = "rng"

    if args.target.lower() not in VALID_TARGETS:
        print(f"  Unknown target: {args.target}")
        print(f"  Valid targets: {', '.join(VALID_TARGETS)}")
        sys.exit(1)

    # RNG mode requires start-ms
    if args.mode == "rng" and args.start_ms is None:
        ms_input = input("  Enter START jitter in ms (from find_shiny_frame.py): ").strip()
        try:
            args.start_ms = int(ms_input)
        except ValueError:
            print(f"  Invalid ms value: {ms_input}")
            sys.exit(1)

    cfg = load_settings()

    # ── Capture ────────────────────────────────────────────────────────
    device_idx = cfg["capture"]["device_index"]
    log.info(f"Opening capture device {device_idx} (OBS Virtual Camera)...")
    capture = CaptureHandler(device_index=device_idx)
    capture.open()

    # Quick sanity check — grab one frame
    time.sleep(1)
    test_frame = capture.grab_frame()
    if test_frame is None:
        log.error("Could not read a frame from the capture device. Is OBS Virtual Camera running?")
        sys.exit(1)
    mean = test_frame.mean()
    h, w = test_frame.shape[:2]
    log.info(f"Capture OK — {w}x{h}, mean brightness={mean:.1f}")
    if mean < 5:
        log.warning("Frame is very dark! Make sure OBS is showing the Switch screen and Virtual Camera is started.")

    # Save a startup screenshot
    os.makedirs("tools/screenshots", exist_ok=True)
    cv2.imwrite("tools/screenshots/hunt_start.png", test_frame)
    log.info("Saved startup frame to tools/screenshots/hunt_start.png")

    # ── Controller ─────────────────────────────────────────────────────
    if args.dry_run:
        log.info("DRY RUN — no Arduino commands will be sent")
        mode = ControllerMode.KEYBOARD   # won't actually press keys without pynput
        port = None
    else:
        mode = ControllerMode.SERIAL
        port = cfg["controller"]["serial_port"]
        log.info(f"Connecting to Arduino on {port}...")

    controller = SwitchController(
        mode=mode,
        port=port or "COM7",
        baud_rate=cfg["controller"].get("baud_rate", 9600),
    )
    if not args.dry_run:
        controller.connect()
        log.info("Controller connected.")
    else:
        log.info("DRY RUN — skipping Arduino connection.")

    # ── Detector ───────────────────────────────────────────────────────
    det_cfg = cfg.get("detection", {})
    detector = ShinyDetector(
        threshold=det_cfg.get("sparkle_threshold", 50),
    )

    # ── Hunt ───────────────────────────────────────────────────────────
    saved_encounters = load_progress(args.target)
    disk_encounters = max_encounter_on_disk(args.target)
    if disk_encounters > saved_encounters:
        log.warning(
            f"Progress file says {saved_encounters} but screenshots go up to "
            f"#{disk_encounters}. Resuming from {disk_encounters} to avoid overwrites."
        )
        saved_encounters = disk_encounters
        save_progress(args.target, saved_encounters)
    if saved_encounters:
        log.info(f"Resuming from saved progress: {saved_encounters} encounters already logged.")

    if args.mode == "rng":
        hunt = RNGHuntSequence(
            target=args.target,
            controller=controller,
            detector=detector,
            capture=capture,
            start_ms=args.start_ms,
            continue_ms=args.continue_ms,
            spread_ms=args.spread,
            step_ms=args.step,
            on_status=on_status,
            on_encounter=on_encounter,
            on_progress=save_progress,
            start_encounters=saved_encounters,
        )
        mode_label = f"RNG  (START=+{args.start_ms}ms, ±{args.spread//2}ms sweep)"
    else:
        hunt = HuntSequence(
            target=args.target,
            controller=controller,
            detector=detector,
            capture=capture,
            on_status=on_status,
            on_encounter=on_encounter,
            on_progress=save_progress,
            start_encounters=saved_encounters,
        )
        mode_label = "Reset (brute-force)"

    log.info(f"\n{'='*50}")
    log.info(f"  Target : {args.target.upper()}")
    log.info(f"  Mode   : {mode_label}")
    log.info(f"  Device : {device_idx}  (OBS Virtual Camera)")
    log.info(f"  Port   : {port or 'DRY RUN'}")
    log.info(f"{'='*50}")
    log.info("Press Ctrl+C to stop the hunt at any time.\n")

    try:
        result = hunt.run()
    except KeyboardInterrupt:
        log.info("\nHunt stopped by user.")
        hunt.stop()
        result = None
    finally:
        save_progress(args.target, hunt.encounters)
        log.info(f"Progress saved: {hunt.encounters} encounters for {args.target}.")
        capture.close()
        controller.disconnect()

    if result and result.is_shiny:
        log.info(f"\n🎉 SHINY found after {result.encounters} encounters!")
        if result.frame is not None:
            path = f"tools/screenshots/shiny_{args.target}.png"
            cv2.imwrite(path, result.frame)
            log.info(f"Screenshot saved: {path}")
    else:
        enc = hunt.encounters
        log.info(f"\nHunt ended. Total encounters: {enc}")

    # Release the sleep prevention
    ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)


if __name__ == "__main__":
    main()
