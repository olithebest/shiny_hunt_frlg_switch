"""
Test shiny detection for all FRLG legendaries by pasting real shiny sprites
onto an actual battle screenshot.

Method:
  1. Take a real Ho-Oh battle screenshot (ho-oh_00001_full.png) as the base
  2. For each legendary, paste its NORMAL sprite into the sprite region -> test as "normal"
  3. Then paste its SHINY sprite into the same region -> test as "shiny" 
  4. Run all detection tiers and report pass/fail

This uses actual FRLG shiny sprites from data/sprites/frlg/shiny/
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np
import logging
from src.detection.shiny_detector import ShinyDetector
from src.detection.shiny_colors import POKEMON_BODY_COLORS, POKEMON_SPRITE_REGION
from src.detection.frlg_palettes import get_palette, classify_hue

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
ENC_DIR = os.path.join(BASE_DIR, "screenshots", "encounters")
SPRITE_DIR = os.path.join(BASE_DIR, "..", "data", "sprites", "frlg")
NORMAL_SPRITE_DIR = os.path.join(SPRITE_DIR, "normal")
SHINY_SPRITE_DIR = os.path.join(SPRITE_DIR, "shiny")
OUTPUT_DIR = os.path.join(BASE_DIR, "screenshots", "detection_tests")

# All legendaries obtainable in FRLG
LEGENDARIES = {
    "articuno":  {"dex": 144, "sprite_name": "144_articuno"},
    "zapdos":    {"dex": 145, "sprite_name": "145_zapdos"},
    "moltres":   {"dex": 146, "sprite_name": "146_moltres"},
    "mewtwo":    {"dex": 150, "sprite_name": "150_mewtwo"},
    "lugia":     {"dex": 249, "sprite_name": "249_lugia"},
    "ho-oh":     {"dex": 250, "sprite_name": "250_ho_oh"},
    "deoxys":    {"dex": 386, "sprite_name": "386_deoxys"},
}


def paste_sprite_onto_battle(base_frame: np.ndarray, sprite_path: str) -> np.ndarray:
    """
    Paste a Pokemon sprite onto the battle screenshot in the sprite region.
    The sprite replaces the existing Pokemon in POKEMON_SPRITE_REGION.
    
    First fills the sprite region with a neutral dark gray to simulate a
    cave-like battle background (most FRLG legendaries are in caves).
    Then pastes the sprite with proper alpha blending.
    """
    frame = base_frame.copy()
    sprite = cv2.imread(sprite_path, cv2.IMREAD_UNCHANGED)  # load with alpha
    if sprite is None:
        raise FileNotFoundError(f"Cannot load sprite: {sprite_path}")
    
    h, w = frame.shape[:2]
    # Sprite region coordinates
    t = int(POKEMON_SPRITE_REGION["top"] * h)
    l = int(POKEMON_SPRITE_REGION["left"] * w)
    b = int(POKEMON_SPRITE_REGION["bottom"] * h)
    r = int(POKEMON_SPRITE_REGION["right"] * w)
    
    region_h = b - t
    region_w = r - l
    
    # Fill the sprite region with neutral dark gray — simulates a cave battle
    # background and prevents the old Ho-Oh pixels from contaminating detection
    frame[t:b, l:r] = (50, 50, 50)
    
    # Resize sprite to fit the region
    sprite_resized = cv2.resize(sprite, (region_w, region_h), interpolation=cv2.INTER_NEAREST)
    
    if sprite_resized.shape[2] == 4:
        # Has alpha channel - blend properly
        alpha = sprite_resized[:, :, 3] / 255.0
        bgr = sprite_resized[:, :, :3]
        
        for c in range(3):
            frame[t:b, l:r, c] = (
                alpha * bgr[:, :, c] +
                (1 - alpha) * frame[t:b, l:r, c]
            ).astype(np.uint8)
    else:
        # No alpha - just paste directly
        frame[t:b, l:r] = sprite_resized[:, :, :3]
    
    return frame


def analyze_detection(detector: ShinyDetector, frame: np.ndarray, target: str, 
                      expected_shiny: bool) -> dict:
    """Run all detection tiers and return results."""
    results = {}
    
    # Tier 2: Palette/dominant hue
    # Try both ho-oh and ho_oh style names
    palette_result = detector.detect_by_dominant_hue(frame, target)
    if palette_result is None:
        alt_name = target.replace("-", "_")
        palette_result = detector.detect_by_dominant_hue(frame, alt_name)
    results["tier2_palette"] = palette_result
    
    # Tier 3: Reference image (skip for Mewtwo — its reference images are
    # calibrated against real Switch captures, not pasted GBA sprites)
    if target.lower() == "mewtwo":
        ref_result = None
    else:
        ref_result = detector.confirm_shiny_by_reference(frame, target)
    results["tier3_reference"] = ref_result
    
    # Tier 4: HSV body color
    color_result = detector.confirm_shiny_by_color(frame, target)
    results["tier4_color"] = color_result
    
    # Get detailed color pixel counts
    profile = POKEMON_BODY_COLORS.get(target.lower())
    if profile:
        h, w = frame.shape[:2]
        t = int(POKEMON_SPRITE_REGION["top"] * h)
        l = int(POKEMON_SPRITE_REGION["left"] * w)
        b = int(POKEMON_SPRITE_REGION["bottom"] * h)
        r = int(POKEMON_SPRITE_REGION["right"] * w)
        region = frame[t:b, l:r]
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        
        shiny_mask = cv2.inRange(hsv, profile["shiny"]["lower"], profile["shiny"]["upper"])
        normal_mask = cv2.inRange(hsv, profile["normal"]["lower"], profile["normal"]["upper"])
        results["shiny_pixels"] = cv2.countNonZero(shiny_mask)
        results["normal_pixels"] = cv2.countNonZero(normal_mask)
    
    # Get dominant hue
    entry = get_palette(target) or get_palette(target.replace("-", "_"))
    if entry:
        h_img, w_img = frame.shape[:2]
        t = int(POKEMON_SPRITE_REGION["top"] * h_img)
        l = int(POKEMON_SPRITE_REGION["left"] * w_img)
        b = int(POKEMON_SPRITE_REGION["bottom"] * h_img)
        r = int(POKEMON_SPRITE_REGION["right"] * w_img)
        region = frame[t:b, l:r]
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        sat_mask = hsv[:, :, 1] >= entry.min_sat
        val_mask = hsv[:, :, 2] >= entry.min_val
        body_mask = sat_mask & val_mask
        body_hues = hsv[:, :, 0][body_mask]
        if len(body_hues) > 0:
            hist = cv2.calcHist([body_hues.reshape(-1, 1).astype(np.float32)],
                                [0], None, [180], [0, 180]).flatten()
            kernel = np.ones(5) / 5
            hist_smooth = np.convolve(hist, kernel, mode='same')
            results["dominant_hue"] = int(np.argmax(hist_smooth))
    
    # Overall: would the full pipeline detect it correctly?
    # Tier 4 is the main one for legendaries without reference images
    correct = False
    if expected_shiny:
        # For shiny: any positive tier = detected
        correct = (results.get("tier4_color") is True or 
                   results.get("tier2_palette") is True or
                   results.get("tier3_reference") is True)
    else:
        # For normal: no tier should say shiny
        correct = (results.get("tier4_color") is not True and
                   results.get("tier2_palette") is not True and
                   results.get("tier3_reference") is not True)
    results["correct"] = correct
    results["expected"] = "SHINY" if expected_shiny else "normal"
    
    return results


def format_result(val):
    if val is True: return "SHINY"
    if val is False: return "normal"
    return "n/a"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    detector = ShinyDetector()
    
    # Load the base battle frame (real Ho-Oh encounter)
    base_path = os.path.join(ENC_DIR, "ho-oh_00001_full.png")
    if not os.path.isfile(base_path):
        print(f"ERROR: Base battle screenshot not found: {base_path}")
        return
    
    base_frame = cv2.imread(base_path)
    print(f"Base frame: ho-oh_00001_full.png ({base_frame.shape[1]}x{base_frame.shape[0]})")
    print()
    
    all_results = []
    
    for target, info in LEGENDARIES.items():
        sprite_name = info["sprite_name"]
        normal_sprite = os.path.join(NORMAL_SPRITE_DIR, f"{sprite_name}.png")
        shiny_sprite = os.path.join(SHINY_SPRITE_DIR, f"{sprite_name}.png")
        
        if not os.path.isfile(normal_sprite):
            print(f"  WARNING: Normal sprite not found: {normal_sprite}")
            continue
        if not os.path.isfile(shiny_sprite):
            print(f"  WARNING: Shiny sprite not found: {shiny_sprite}")
            continue
        
        print(f"{'='*70}")
        print(f"  {target.upper()} (#{info['dex']})")
        print(f"{'='*70}")
        
        # Test with NORMAL sprite pasted in
        normal_frame = paste_sprite_onto_battle(base_frame, normal_sprite)
        cv2.imwrite(os.path.join(OUTPUT_DIR, f"{target}_test_normal.png"), normal_frame)
        
        normal_results = analyze_detection(detector, normal_frame, target, expected_shiny=False)
        
        print(f"  NORMAL sprite pasted:")
        print(f"    Tier 2 (palette):   {format_result(normal_results['tier2_palette'])}")
        print(f"    Tier 3 (reference): {format_result(normal_results['tier3_reference'])}")
        print(f"    Tier 4 (HSV color): {format_result(normal_results['tier4_color'])}")
        if "shiny_pixels" in normal_results:
            print(f"    Pixel counts:       shiny={normal_results['shiny_pixels']}, normal={normal_results['normal_pixels']}")
        if "dominant_hue" in normal_results:
            print(f"    Dominant hue:       {normal_results['dominant_hue']}")
        status = "PASS" if normal_results["correct"] else "FAIL"
        print(f"    Expected: normal -> {status}")
        
        # Test with SHINY sprite pasted in
        shiny_frame = paste_sprite_onto_battle(base_frame, shiny_sprite)
        cv2.imwrite(os.path.join(OUTPUT_DIR, f"{target}_test_shiny.png"), shiny_frame)
        
        shiny_results = analyze_detection(detector, shiny_frame, target, expected_shiny=True)
        
        print(f"  SHINY sprite pasted:")
        print(f"    Tier 2 (palette):   {format_result(shiny_results['tier2_palette'])}")
        print(f"    Tier 3 (reference): {format_result(shiny_results['tier3_reference'])}")
        print(f"    Tier 4 (HSV color): {format_result(shiny_results['tier4_color'])}")
        if "shiny_pixels" in shiny_results:
            print(f"    Pixel counts:       shiny={shiny_results['shiny_pixels']}, normal={shiny_results['normal_pixels']}")
        if "dominant_hue" in shiny_results:
            print(f"    Dominant hue:       {shiny_results['dominant_hue']}")
        status = "PASS" if shiny_results["correct"] else "FAIL"
        print(f"    Expected: SHINY -> {status}")
        print()
        
        all_results.append({
            "target": target,
            "normal_correct": normal_results["correct"],
            "shiny_correct": shiny_results["correct"],
            "normal_tier4": normal_results.get("tier4_color"),
            "shiny_tier4": shiny_results.get("tier4_color"),
            "normal_tier2": normal_results.get("tier2_palette"),
            "shiny_tier2": shiny_results.get("tier2_palette"),
            "normal_tier3": normal_results.get("tier3_reference"),
            "shiny_tier3": shiny_results.get("tier3_reference"),
        })
    
    # === Final Summary ===
    print(f"{'='*70}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Pokemon':<12} {'Normal?':<10} {'Shiny?':<10} {'T2 Palette':<12} {'T3 Ref':<10} {'T4 Color':<12} {'Status'}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*12} {'-'*10} {'-'*12} {'-'*8}")
    
    total_pass = 0
    total_tests = 0
    for r in all_results:
        normal_ok = "PASS" if r["normal_correct"] else "FAIL"
        shiny_ok = "PASS" if r["shiny_correct"] else "FAIL"
        both_ok = r["normal_correct"] and r["shiny_correct"]
        status = "OK" if both_ok else "BROKEN"
        
        # What tier(s) detected the shiny?
        detected_by = []
        if r["shiny_tier2"] is True: detected_by.append("T2")
        if r["shiny_tier3"] is True: detected_by.append("T3")
        if r["shiny_tier4"] is True: detected_by.append("T4")
        detection_str = ",".join(detected_by) if detected_by else "NONE"
        
        print(f"  {r['target']:<12} {normal_ok:<10} {shiny_ok:<10} "
              f"{format_result(r['shiny_tier2']):<12} "
              f"{format_result(r['shiny_tier3']):<12} "
              f"{format_result(r['shiny_tier4']):<10} "
              f"{status} (by {detection_str})")
        
        if r["normal_correct"]: total_pass += 1
        if r["shiny_correct"]: total_pass += 1
        total_tests += 2
    
    print()
    print(f"  Total: {total_pass}/{total_tests} tests passed")
    print(f"  Test images saved to: {os.path.abspath(OUTPUT_DIR)}")
    
    # List any failures
    failures = [r for r in all_results if not (r["normal_correct"] and r["shiny_correct"])]
    if failures:
        print()
        print(f"  FAILURES that need fixing:")
        for r in failures:
            issues = []
            if not r["normal_correct"]: issues.append("false positive on normal")
            if not r["shiny_correct"]: issues.append("missed shiny") 
            print(f"    {r['target']}: {', '.join(issues)}")
    else:
        print(f"\n  All legendaries: detection working correctly!")


if __name__ == "__main__":
    main()
