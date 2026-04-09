"""
Test Ho-Oh shiny detection on real encounter screenshots.
Validates each detection tier independently + tests with a hue-shifted "fake shiny".
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np
import logging
from src.detection.shiny_detector import ShinyDetector
from src.detection.shiny_colors import POKEMON_BODY_COLORS, POKEMON_SPRITE_REGION
from src.detection.frlg_palettes import get_palette, classify_hue

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ENC_DIR = os.path.join(os.path.dirname(__file__), "screenshots", "encounters")

def analyze_sprite_colors(frame, target="ho-oh"):
    """Detailed HSV analysis of the sprite region."""
    h, w = frame.shape[:2]
    t = int(POKEMON_SPRITE_REGION["top"] * h)
    l = int(POKEMON_SPRITE_REGION["left"] * w)
    b = int(POKEMON_SPRITE_REGION["bottom"] * h)
    r = int(POKEMON_SPRITE_REGION["right"] * w)
    region = frame[t:b, l:r]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    
    profile = POKEMON_BODY_COLORS.get(target.lower())
    if not profile:
        print(f"  No color profile for {target}")
        return
    
    shiny_mask = cv2.inRange(hsv, profile["shiny"]["lower"], profile["shiny"]["upper"])
    normal_mask = cv2.inRange(hsv, profile["normal"]["lower"], profile["normal"]["upper"])
    shiny_px = cv2.countNonZero(shiny_mask)
    normal_px = cv2.countNonZero(normal_mask)
    
    # Also get dominant hue of colored body pixels
    sat_mask = hsv[:, :, 1] >= 100
    val_mask = hsv[:, :, 2] >= 100
    body_mask = sat_mask & val_mask
    body_hues = hsv[:, :, 0][body_mask]
    
    hist = cv2.calcHist([body_hues.reshape(-1, 1).astype(np.float32)],
                        [0], None, [180], [0, 180]).flatten()
    kernel = np.ones(5) / 5
    hist_smooth = np.convolve(hist, kernel, mode='same')
    dominant_hue = int(np.argmax(hist_smooth))
    
    print(f"  Sprite analysis:")
    print(f"    Normal pixels (H 0-15): {normal_px}")
    print(f"    Shiny pixels  (H 15-35): {shiny_px}")
    print(f"    Dominant body hue: {dominant_hue}")
    print(f"    Body pixel count: {len(body_hues)}")
    print(f"    Tier 4 verdict: {'SHINY' if (shiny_px >= 50 and shiny_px > normal_px) else 'normal'}")
    
    # Hue distribution in 5-degree buckets
    print(f"    Hue distribution (body pixels):")
    for start in range(0, 40, 5):
        count = int(np.sum((body_hues >= start) & (body_hues < start + 5)))
        bar = '#' * (count // 20)
        print(f"      H {start:3d}-{start+4:3d}: {count:5d} {bar}")
    return normal_px, shiny_px, dominant_hue

def make_fake_shiny(frame, hue_shift=15):
    """Shift hue of an image to simulate shiny Ho-Oh (more gold/yellow)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Only shift pixels that are in the red/orange range (H < 20)
    mask = hsv[:, :, 0] < 20
    hsv[:, :, 0] = np.where(mask, 
                             np.clip(hsv[:, :, 0].astype(int) + hue_shift, 0, 179).astype(np.uint8),
                             hsv[:, :, 0])
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def main():
    detector = ShinyDetector()
    
    # Find first available encounter
    test_file = None
    for i in range(1, 100):
        path = os.path.join(ENC_DIR, f"ho-oh_{i:05d}_full.png")
        if os.path.isfile(path):
            test_file = path
            break
    
    if not test_file:
        print("ERROR: No Ho-Oh encounter screenshots found!")
        return
    
    frame = cv2.imread(test_file)
    print(f"Testing with: {os.path.basename(test_file)}")
    print(f"Image size: {frame.shape[1]}x{frame.shape[0]}")
    print()
    
    # === Test 1: Normal Ho-Oh - detailed color analysis ===
    print("=" * 60)
    print("TEST 1: Normal Ho-Oh sprite color analysis")
    print("=" * 60)
    analyze_sprite_colors(frame)
    print()
    
    # === Test 2: Run palette/hue detection (Tier 2) ===
    print("=" * 60)
    print("TEST 2: Palette/dominant hue detection (Tier 2)")
    print("=" * 60)
    entry = get_palette("ho-oh")  # tries ho-oh first, then ho_oh
    if entry is None:
        entry = get_palette("ho_oh")
    if entry:
        print(f"  Palette entry found: normal={entry.normal_hues}, shiny={entry.shiny_hues}, subtle={entry.subtle}")
        # Manual hue check
        from src.detection.shiny_detector import ShinyDetector as SD
        d = SD()
        result = d.detect_by_dominant_hue(frame, "ho-oh")
        if result is None:
            result = d.detect_by_dominant_hue(frame, "ho_oh")
        print(f"  Tier 2 result: {result} ({'SHINY' if result else 'normal' if result is False else 'inconclusive'})")
    else:
        print("  No palette entry found for ho-oh or ho_oh!")
    print()
    
    # === Test 3: Reference image check (Tier 3) ===
    print("=" * 60)
    print("TEST 3: Reference image comparison (Tier 3)")
    print("=" * 60)
    ref_result = detector.confirm_shiny_by_reference(frame, "ho-oh")
    print(f"  Tier 3 result: {ref_result} ({'SHINY' if ref_result else 'normal' if ref_result is False else 'NO REFERENCE IMAGES'})")
    print()
    
    # === Test 4: HSV body color check (Tier 4) ===
    print("=" * 60)
    print("TEST 4: HSV body color range check (Tier 4)")
    print("=" * 60)
    color_result = detector.confirm_shiny_by_color(frame, "ho-oh")
    print(f"  Tier 4 result: {color_result} ({'SHINY' if color_result else 'normal' if color_result is False else 'n/a'})")
    print()
    
    # === Test 5: Full check_window on normal Ho-Oh ===
    print("=" * 60)
    print("TEST 5: Full check_window() on normal Ho-Oh (single frame)")
    print("=" * 60)
    result = detector.check_window([frame], target="ho-oh", encounter=99999)
    print(f"  is_shiny={result.is_shiny}, confidence={result.confidence}")
    print(f"  sparkle_triggered={result.sparkle_triggered}")
    print(f"  color_confirmed={result.color_confirmed}")
    print()
    
    # === Test 6: Simulated shiny Ho-Oh ===
    print("=" * 60)
    print("TEST 6: Simulated SHINY Ho-Oh (hue-shifted +15)")
    print("=" * 60)
    fake_shiny = make_fake_shiny(frame, hue_shift=15)
    cv2.imwrite(os.path.join(ENC_DIR, "ho-oh_FAKE_SHINY.png"), fake_shiny)
    print("  Saved fake shiny to ho-oh_FAKE_SHINY.png")
    analyze_sprite_colors(fake_shiny)
    print()
    color_result_shiny = detector.confirm_shiny_by_color(fake_shiny, "ho-oh")
    print(f"  Tier 4 on fake shiny: {color_result_shiny} ({'SHINY' if color_result_shiny else 'normal' if color_result_shiny is False else 'n/a'})")
    
    ref_result_shiny = detector.confirm_shiny_by_reference(fake_shiny, "ho-oh")
    print(f"  Tier 3 on fake shiny: {ref_result_shiny} (no ref = None)")
    
    result_shiny = detector.check_window([fake_shiny], target="ho-oh", encounter=99998)
    print(f"  Full result: is_shiny={result_shiny.is_shiny}, color_confirmed={result_shiny.color_confirmed}")
    print()
    
    # === Summary ===
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Tier 1 (sparkle anim):  Only works with multiple frames during sparkle sequence")
    print(f"  Tier 2 (palette hue):   {'BROKEN' if entry and entry.subtle else 'Works'} - ranges overlap, subtle=True")
    print(f"  Tier 3 (reference img): NO REFERENCE IMAGES for Ho-Oh")
    tier4_ok = color_result is False  # normal should be False, not None
    print(f"  Tier 4 (HSV body):      {'OK - correctly identifies normal' if tier4_ok else 'ISSUE - returns ' + str(color_result)}")
    tier4_shiny_ok = color_result_shiny is True
    print(f"  Tier 4 (fake shiny):    {'OK - correctly identifies shiny' if tier4_shiny_ok else 'ISSUE - returns ' + str(color_result_shiny)}")
    print(f"  Tier 5 (sparkle px):    Only contributes if another tier agrees")
    
    if tier4_ok and tier4_shiny_ok:
        print()
        print("  >>> Tier 4 (HSV body color) CAN distinguish normal vs shiny Ho-Oh!")
        print("  >>> Detection should work, but adding reference images would make it more robust.")
    elif not tier4_ok or not tier4_shiny_ok:
        print()
        print("  >>> WARNING: Tier 4 cannot reliably distinguish Ho-Oh shinies!")
        print("  >>> Reference images (Tier 3) are NEEDED before hunting.")

if __name__ == "__main__":
    main()
