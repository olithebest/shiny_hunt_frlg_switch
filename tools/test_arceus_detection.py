"""
Test Arceus (BDSP) shiny detection.

Usage:
    # Grab a LIVE frame from the capture card and test it:
    python tools/test_arceus_detection.py

    # Test on a saved screenshot:
    python tools/test_arceus_detection.py path/to/screenshot.png

    # Specify capture card device index (default 0):
    python tools/test_arceus_detection.py --device 1

What this does:
    1. Captures one frame from your capture card (or loads a file)
    2. Overlays the detection region on the frame so you can see exactly what the
       bot is looking at
    3. Counts gold/yellow HSV pixels (shiny Arceus is golden, normal is white)
    4. Shows a side-by-side debug window:
         LEFT  = full frame with detection box drawn in green
         RIGHT = isolated gold-pixel mask (white = gold region found)
    5. Prints the pixel count and current threshold to the console

Controls:
    Press any key to close the debug window.
    The frame is also saved to tools/screenshots/detection_tests/arceus_test.png
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np

from src.capture.capture_handler import CaptureHandler
from src.automation.sequences import BDSPHuntConfig

# ---------------------------------------------------------------------------
# Config — must match BDSPHuntConfig defaults exactly
# ---------------------------------------------------------------------------
CFG = BDSPHuntConfig()

# All values come directly from BDSPHuntConfig — guaranteed to stay in sync with live detection
GOLD_LO   = np.array([CFG.gold_h_lo, CFG.gold_s_lo, CFG.gold_v_lo], dtype=np.uint8)
GOLD_HI   = np.array([CFG.gold_h_hi, 255,            255           ], dtype=np.uint8)
THRESHOLD = CFG.gold_pixel_threshold

# ---------------------------------------------------------------------------

def analyze_frame(frame: np.ndarray) -> dict:
    """Run the exact same detection logic as BDSPHuntSequence._check_shiny()."""
    h, w = frame.shape[:2]
    # Read region bounds from config — always in sync with the live hunt
    y0 = int(CFG.body_y_lo * h)
    y1 = int(CFG.body_y_hi * h)
    x0 = int(CFG.body_x_lo * w)
    x1 = int(CFG.body_x_hi * w)
    region = frame[y0:y1, x0:x1]

    hsv  = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, GOLD_LO, GOLD_HI)
    count = int(cv2.countNonZero(mask))

    # Build a full-frame mask image for display
    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[y0:y1, x0:x1] = mask

    return {
        "count":      count,
        "is_shiny":   count >= THRESHOLD,
        "region_box": (x0, y0, x1, y1),
        "mask":       full_mask,
        "region":     region,
    }


def build_debug_image(frame: np.ndarray, result: dict) -> np.ndarray:
    """Draw detection box on frame and create side-by-side debug image."""
    vis = frame.copy()
    x0, y0, x1, y1 = result["region_box"]

    color = (0, 255, 0) if result["is_shiny"] else (0, 120, 255)
    cv2.rectangle(vis, (x0, y0), (x1, y1), color, 3)

    label = f"GOLD px: {result['count']} / {THRESHOLD}  →  {'✓ SHINY!' if result['is_shiny'] else '✗ normal'}"
    cv2.putText(vis, label, (x0, max(y0 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)

    # Right panel: show the gold mask in yellow on black
    mask_bgr = cv2.cvtColor(result["mask"], cv2.COLOR_GRAY2BGR)
    mask_bgr[result["mask"] > 0] = [0, 220, 255]  # yellow highlights

    # Resize both to same height
    target_h = max(vis.shape[0], mask_bgr.shape[0])
    if vis.shape[0] != target_h:
        vis = cv2.resize(vis, (int(vis.shape[1] * target_h / vis.shape[0]), target_h))
    if mask_bgr.shape[0] != target_h:
        mask_bgr = cv2.resize(mask_bgr, (int(mask_bgr.shape[1] * target_h / mask_bgr.shape[0]), target_h))

    combined = np.hstack([vis, mask_bgr])
    return combined


def print_hue_distribution(region: np.ndarray):
    """Print a hue histogram of the detection region to help calibrate thresholds."""
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    # Only look at pixels with decent saturation + brightness (ignore white/black)
    s_mask = hsv[:, :, 1] > 60
    v_mask = hsv[:, :, 2] > 60
    body = hsv[:, :, 0][s_mask & v_mask]

    if len(body) == 0:
        print("  (No saturated pixels found in region — Arceus may not be in battle yet)")
        return

    print(f"\n  Hue distribution of saturated pixels in detection region ({len(body)} total):")
    for start in range(0, 65, 5):
        count = int(np.sum((body >= start) & (body < start + 5)))
        bar = "█" * min(count // 30, 40)
        marker = " ← GOLD TARGET" if CFG.gold_h_lo <= start < CFG.gold_h_hi else ""
        print(f"    H {start:3d}-{start+4:3d}: {count:5d}  {bar}{marker}")


def main():
    parser = argparse.ArgumentParser(description="Test Arceus BDSP shiny detection")
    parser.add_argument("image", nargs="?", help="Path to a screenshot (optional)")
    parser.add_argument("--device", type=int, default=0, help="Capture card device index")
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load frame
    # -----------------------------------------------------------------------
    if args.image:
        print(f"Loading image: {args.image}")
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"ERROR: Could not load '{args.image}'")
            sys.exit(1)
    else:
        print(f"Grabbing live frame from capture card (device {args.device})...")
        with CaptureHandler(device_index=args.device) as cap:
            frame = cap.grab_frame()
        if frame is None:
            print("ERROR: Could not grab frame. Check your capture card device index.")
            sys.exit(1)
        print("Frame captured.")

    # -----------------------------------------------------------------------
    # Run detection
    # -----------------------------------------------------------------------
    result = analyze_frame(frame)

    print("\n" + "=" * 60)
    print("  ARCEUS SHINY DETECTION TEST")
    print("=" * 60)
    print(f"  Gold pixels found : {result['count']}")
    print(f"  Threshold         : {THRESHOLD}")
    print(f"  Gold HSV range    : H {CFG.gold_h_lo}-{CFG.gold_h_hi}, S≥{CFG.gold_s_lo}, V≥{CFG.gold_v_lo}")
    print(f"  VERDICT           : {'🌟 SHINY (golden Arceus detected)' if result['is_shiny'] else '✗ Normal (white Arceus)'}")
    print("=" * 60)

    print_hue_distribution(result["region"])

    # -----------------------------------------------------------------------
    # Save + display
    # -----------------------------------------------------------------------
    out_dir = os.path.join(os.path.dirname(__file__), "screenshots", "detection_tests")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "arceus_test.png")

    debug_img = build_debug_image(frame, result)
    cv2.imwrite(out_path, debug_img)
    print(f"\n  Debug image saved to: {out_path}")

    print("\n  Showing debug window — press any key to close.")
    print("    LEFT  = frame with detection box (green=shiny, orange=normal)")
    print("    RIGHT = gold pixel mask (yellow highlights = gold pixels found)")

    cv2.imshow("Arceus Detection Test", debug_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    print("\nDone.")


if __name__ == "__main__":
    main()
