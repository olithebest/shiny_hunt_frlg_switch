"""
Seed Sweep Tool
===============
Tries multiple timing variations around known jitter values to recover a shiny.
Useful when the exact ms values are known but Windows timer resolution (~15ms)
may have caused slight drift from the target frame.

Each run uses slightly different START/CONTINUE delays covering ±N frames
around the target, maximising the chance of hitting the exact shiny seed.

Usage:
    # Auto mode — runs all 3 phases sequentially, stops on shiny (RECOMMENDED):
    C:\\Python310\\python.exe tools/sweep_seed.py --start-ms 402 --continue-ms 221 --auto

    # Manual single-phase:
    C:\\Python310\\python.exe tools/sweep_seed.py --start-ms 402 --continue-ms 221 --start-only
    C:\\Python310\\python.exe tools/sweep_seed.py --start-ms 402 --continue-ms 221 --spread 160 --step 8

Arguments:
    --start-ms      Target START jitter in milliseconds (from the log)
    --continue-ms   Target CONTINUE jitter in milliseconds (from the log)
    --spread        Total ms range to sweep around each target (default: 96 = ±48ms = ±3 frames)
    --step          ms step between attempts (default: 16ms = ~1 GBA frame at 60fps)
    --runs          Maximum number of attempts before stopping (default: all combinations)
    --start-only    Only vary the START jitter (faster, START is the most critical)
    --auto          Run 3 escalating phases automatically (recommended for recovery)
    --target        Pokemon target (default: mewtwo)
    --pause         Seconds to pause between runs (default: 0)

Auto phases:
    Phase 1 — START only,  ±48ms, 16ms step (7 attempts, fastest)
    Phase 2 — START only,  ±80ms,  8ms step (adds 14 more attempts, finer resolution)
    Phase 3 — START+CONTINUE, ±48ms, 16ms step (adds up to 42 more 2D combos)
"""

import sys
import os
import argparse
import csv
import logging
import time
import yaml
import itertools

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.capture.capture_handler import CaptureHandler
from src.controller.switch_controller import SwitchController, ControllerMode
from src.detection.shiny_detector import ShinyDetector
from src.automation.sequences import HuntConfig, _TARGET_CONFIGS
from src.controller.switch_controller import Button

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_settings(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def ms_range(center_ms: int, spread_ms: int, step_ms: int) -> list[int]:
    """Return a list of ms values centered on center_ms ±spread_ms/2 in step_ms increments."""
    half = spread_ms // 2
    values = list(range(max(0, center_ms - half), center_ms + half + 1, step_ms))
    # Sort so center value is tried first, then alternating ±
    values.sort(key=lambda x: abs(x - center_ms))
    return values


def run_one_attempt(
    controller,
    capture: CaptureHandler,
    detector: ShinyDetector,
    config: HuntConfig,
    target: str,
    start_ms: int,
    continue_ms: int,
    attempt_num: int,
    total: int,
    csv_writer=None,
) -> bool:
    """
    Run one full reset → detect cycle with fixed jitter values.
    Returns True if shiny detected, False otherwise.
    """
    log.info(f"[{attempt_num}/{total}] START=+{start_ms}ms  CONTINUE=+{continue_ms}ms")

    # Soft reset
    controller.soft_reset()
    time.sleep(config.intro_wait)

    controller.press(Button.A, hold_time=0.1, wait_after=0.5)
    controller.press(Button.A, hold_time=0.1, wait_after=0.5)
    time.sleep(config.title_appear_wait)

    # Fixed START jitter
    time.sleep(start_ms / 1000.0)
    controller.press(Button.A)
    time.sleep(config.menu_wait)

    # Fixed CONTINUE jitter
    time.sleep(continue_ms / 1000.0)
    controller.press(Button.A)
    time.sleep(2.0)

    # Skip memories
    for _ in range(config.memories_b_presses):
        controller.press(Button.B, hold_time=0.1, wait_after=config.memories_b_interval)
    time.sleep(config.world_load_wait)

    # Interact with target
    controller.press(Button.A, hold_time=0.15, wait_after=0.3)
    time.sleep(config.navigate_to_target_wait)

    # Sparkle window
    if config.cry_wait > 0:
        time.sleep(config.cry_wait)
        controller.press(Button.A)

    time.sleep(config.battle_start_wait)
    time.sleep(config.sparkle_window_start)

    frames = []
    interval = 1.0 / 10
    end_time = time.time() + config.sparkle_window_duration
    while time.time() < end_time:
        frame = capture.grab_frame()
        if frame is not None:
            frames.append(frame)
        time.sleep(interval)

    enc_num = 90000 + attempt_num
    result = detector.check_window(frames, target=target, encounter=enc_num)
    screenshot = f"{target}_{enc_num:04d}_full.png"
    log.info(f"  → {'*** SHINY! ***' if result.is_shiny else 'not shiny'}  ({screenshot})")
    if csv_writer is not None:
        csv_writer.writerow({
            "attempt": attempt_num,
            "start_ms": start_ms,
            "continue_ms": continue_ms,
            "is_shiny": result.is_shiny,
            "screenshot": screenshot,
        })
    return result.is_shiny


def main():
    parser = argparse.ArgumentParser(
        description="Sweep timing variations to recover a shiny seed"
    )
    parser.add_argument("--start-ms",     type=int, required=True,
                        help="Target START jitter ms from the log (e.g. 402)")
    parser.add_argument("--continue-ms",  type=int, required=True,
                        help="Target CONTINUE jitter ms from the log (e.g. 221)")
    parser.add_argument("--spread",       type=int, default=96,
                        help="Total ms range to sweep around each target (default: 96 = ±48ms = ±3 frames)")
    parser.add_argument("--step",         type=int, default=16,
                        help="Step between attempts in ms (default: 16 = 1 GBA frame)")
    parser.add_argument("--runs",         type=int, default=None,
                        help="Max attempts before stopping (default: all combinations)")
    parser.add_argument("--start-only",   action="store_true",
                        help="Only vary START jitter, keep CONTINUE fixed (fewer runs)")
    parser.add_argument("--auto",         action="store_true",
                        help="Run 3 escalating phases automatically (recommended)")
    parser.add_argument("--target",       default="mewtwo",
                        help="Pokemon target (default: mewtwo)")
    parser.add_argument("--pause",        type=float, default=0.0,
                        help="Extra pause between runs in seconds (default: 0)")
    parser.add_argument("--device",       type=int, default=None,
                        help="OBS camera device index (default: from config)")
    args = parser.parse_args()

    cfg = load_settings()
    config = _TARGET_CONFIGS.get(args.target, HuntConfig())

    # ------------------------------------------------------------------ #
    #  Build combo list(s)                                                 #
    # ------------------------------------------------------------------ #
    if args.auto:
        # Phase 1: START-only, ±48ms, 16ms step (7 attempts)
        p1_starts    = ms_range(args.start_ms,    96,  16)
        p1_continues = [args.continue_ms]
        p1 = list(itertools.product(p1_starts, p1_continues))

        # Phase 2: START-only, ±80ms, 8ms step — deduplicated vs phase 1
        p2_starts    = ms_range(args.start_ms,   160,   8)
        p2_continues = [args.continue_ms]
        p2_all = list(itertools.product(p2_starts, p2_continues))
        p2 = [c for c in p2_all if c not in set(p1)]

        # Phase 3: START+CONTINUE 2D sweep, ±48ms, 16ms step — deduplicated
        p3_starts    = ms_range(args.start_ms,    96,  16)
        p3_continues = ms_range(args.continue_ms, 96,  16)
        p3_all = list(itertools.product(p3_starts, p3_continues))
        seen = set(p1) | set(p2)
        p3 = [c for c in p3_all if c not in seen]

        phases = [
            ("Phase 1 — START only,  ±48ms, 16ms step", p1),
            ("Phase 2 — START only,  ±80ms,  8ms step", p2),
            ("Phase 3 — START+CONTINUE 2D, ±48ms, 16ms step", p3),
        ]
        total = sum(len(ph[1]) for ph in phases)
    else:
        # Manual single-phase (original behaviour)
        start_values    = ms_range(args.start_ms,    args.spread, args.step)
        continue_values = ms_range(args.continue_ms, args.spread, args.step) if not args.start_only else [args.continue_ms]
        combos = sorted(
            list(itertools.product(start_values, continue_values)),
            key=lambda c: abs(c[0] - args.start_ms) + abs(c[1] - args.continue_ms)
        )
        if args.runs:
            combos = combos[:args.runs]
        phases = [("Single phase", combos)]
        total = len(combos)

    # ------------------------------------------------------------------ #
    #  Banner                                                              #
    # ------------------------------------------------------------------ #
    print()
    print("=" * 60)
    print("  SEED SWEEP — Shiny Recovery")
    print("=" * 60)
    print(f"  Target:          {args.target.title()}")
    print(f"  CENTER START:    +{args.start_ms}ms")
    print(f"  CENTER CONTINUE: +{args.continue_ms}ms")
    if args.auto:
        print()
        for label, ph in phases:
            print(f"  {label}  ({len(ph)} attempts)")
    else:
        print(f"  Spread:          ±{args.spread//2}ms")
        print(f"  Step:            {args.step}ms (~1 GBA frame)")
    print()
    print(f"  TOTAL attempts:  {total}")
    print()
    print("  Attempts are ordered closest-to-original first.")
    print("  The bot will STOP the moment a shiny is detected.")
    print()
    print("  IMPORTANT: Your save must be immediately before Mewtwo.")
    print("  DO NOT touch your Switch or PC while this runs!")
    print()
    input("  Press ENTER to start the sweep...")

    # Open camera
    device_idx = args.device if args.device is not None else cfg["capture"]["device_index"]
    capture = CaptureHandler(device_index=device_idx)
    capture.open()
    time.sleep(1)
    test_frame = capture.grab_frame()
    if test_frame is None:
        log.error("No frame from camera. Is OBS Virtual Camera running?")
        sys.exit(1)
    log.info(f"Camera OK — {test_frame.shape[1]}x{test_frame.shape[0]}")

    # Open controller
    port = cfg["controller"]["serial_port"]
    baud = cfg["controller"]["baud_rate"]
    controller = SwitchController(mode=ControllerMode.SERIAL, port=port, baud_rate=baud)
    controller.connect()
    log.info(f"Controller connected on {port}")

    detector = ShinyDetector()

    # CSV log — one row per attempt so you can review results + match screenshots
    enc_dir = os.path.join(os.path.dirname(__file__), "screenshots", "encounters")
    os.makedirs(enc_dir, exist_ok=True)
    csv_path = os.path.join(enc_dir, "sweep_log.csv")
    csv_file = open(csv_path, "w", newline="", encoding="utf-8")
    csv_fields = ["attempt", "start_ms", "continue_ms", "is_shiny", "screenshot"]
    csv_writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
    csv_writer.writeheader()
    log.info(f"Sweep log: {csv_path}")

    try:
        attempt_num = 0
        found = False

        for phase_label, combos in phases:
            if not combos:
                continue
            if args.auto:
                print()
                print(f"  --- {phase_label} ({len(combos)} attempts) ---")

            for s_ms, c_ms in combos:
                attempt_num += 1
                found = run_one_attempt(
                    controller=controller,
                    capture=capture,
                    detector=detector,
                    config=config,
                    target=args.target,
                    start_ms=s_ms,
                    continue_ms=c_ms,
                    attempt_num=attempt_num,
                    total=total,
                    csv_writer=csv_writer,
                )
                csv_file.flush()  # write to disk immediately

                if found:
                    print()
                    print("=" * 60)
                    print("  *** SHINY DETECTED! ***")
                    print(f"  START jitter used:    +{s_ms}ms")
                    print(f"  CONTINUE jitter used: +{c_ms}ms")
                    print()
                    print("  DO NOT restart! Catch it now in-game!")
                    print("  The sweep has stopped — you're in control.")
                    print("=" * 60)
                    return

                if args.pause > 0:
                    time.sleep(args.pause)

        print()
        print("=" * 60)
        print(f"  Sweep complete — {attempt_num} attempts, no shiny found.")
        print()
        print("  The seed may have been beyond the swept range.")
        if not args.auto:
            print("  Try:  --auto  to run all 3 phases automatically.")
        else:
            print("  All 3 phases exhausted. The shiny seed is likely out of reach.")
            print("  Resume the normal hunt — detection is fixed for next time.")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n  Sweep stopped by user.")
    finally:
        csv_file.close()
        capture.close()
        controller.disconnect()


if __name__ == "__main__":
    main()
