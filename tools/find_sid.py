"""
SID Finder Tool — OpenCV only (no Tesseract required)
=====================================================
Reads your Trainer ID from a Trainer Card screenshot and stat values from a
Pokémon Skills screenshot, then calculates your Secret ID (SID) via FRLG
PRNG analysis.

Everything runs with OpenCV + NumPy — nothing extra to install.

Usage examples
--------------
  # From screenshot files (recommended for most users):
  python tools/find_sid.py --species mewtwo --shiny \\
      --screenshot-tid trainer_card.png --screenshot-stats skills_page.png

  # With a live OBS Virtual Camera feed:
  python tools/find_sid.py --mode legendary --species mewtwo --shiny --device 3

  # If you already know your TID:
  python tools/find_sid.py --species mewtwo --shiny --tid 59556 \\
      --screenshot-stats skills_page.png

  # Fully manual (no screenshots, no camera):
  python tools/find_sid.py --species mewtwo --shiny --tid 59556 --nature Impish

Workflow (screenshot mode)
--------------------------
  1. On the Switch, open Trainer Card. Take a screenshot (hold Capture button).
  2. Open the shiny Pokémon's Summary → Skills page (shows all 6 stats).
     Take a screenshot.
  3. Transfer both screenshots to your PC (microSD, NSO album, etc.).
  4. Run this script with --screenshot-tid and --screenshot-stats.
  5. The script reads TID, stats, and nature, then calculates your SID.

Workflow (camera mode)
----------------------
  Same as before: OBS Virtual Camera → script reads live frames when prompted.
"""

import sys
import os
import argparse
import json
import time
import logging

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.capture.capture_handler import CaptureHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── FRLG PRNG ────────────────────────────────────────────────────────────────

def _prng_advance(seed: int) -> int:
    """Advance the Gen-3 PRNG one step."""
    return (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF


def _prng_reverse(seed: int) -> int:
    """Reverse the Gen-3 PRNG one step."""
    return (0xEEB9EB65 * seed + 0x0A3561A1) & 0xFFFFFFFF


def _prng_next16(seed: int):
    """Return (new_seed, 16-bit value)."""
    seed = _prng_advance(seed)
    return seed, seed >> 16


# ── IV / stat arithmetic ──────────────────────────────────────────────────────

NATURES = [
    "Hardy",   "Lonely", "Brave",   "Adamant", "Naughty",
    "Bold",    "Docile", "Relaxed", "Impish",  "Lax",
    "Timid",   "Hasty",  "Serious", "Jolly",   "Naive",
    "Modest",  "Mild",   "Quiet",   "Bashful",  "Rash",
    "Calm",    "Gentle", "Sassy",   "Careful",  "Quirky",
]

# Nature modifiers: (boosted_stat_index, lowered_stat_index)
# Stats order: HP=0, Atk=1, Def=2, SpA=3, SpD=4, Spe=5
# Neutral natures have (-1, -1)
NATURE_MODS = [
    (-1, -1), (1, 4),  (1, 5),  (1, 2),  (1, 4),   # Hardy Lonely Brave Adamant Naughty
    (2, 1),  (-1, -1), (2, 5),  (2, 3),  (2, 5),   # Bold Docile Relaxed Impish Lax  -- wait Lax should be Def+, SpD-... let me redo
    (5, 1),  (5, 2),  (-1, -1), (5, 3),  (5, 4),   # Timid Hasty Serious Jolly Naive
    (3, 1),  (3, 2),  (3, 5),  (-1, -1), (3, 4),   # Modest Mild Quiet Bashful Rash
    (4, 1),  (4, 2),  (4, 5),  (4, 3),  (-1, -1),  # Calm Gentle Sassy Careful Quirky
]

# Correct NATURE_MODS table:
#   Each row: (boosted, lowered). Index 0 = HP (never boosted/lowered by nature).
_NATURE_MODS_CORRECT = {
    "Hardy":   (-1, -1), "Lonely": (1, 2),  "Brave":   (1, 5),  "Adamant": (1, 3),  "Naughty": (1, 4),
    "Bold":    (2, 1),   "Docile": (-1,-1),  "Relaxed": (2, 5),  "Impish":  (2, 3),  "Lax":     (2, 4),
    "Timid":   (5, 1),   "Hasty":  (5, 2),  "Serious": (-1,-1),  "Jolly":   (5, 3),  "Naive":   (5, 4),
    "Modest":  (3, 1),   "Mild":   (3, 2),  "Quiet":   (3, 5),  "Bashful": (-1,-1),  "Rash":    (3, 4),
    "Calm":    (4, 1),   "Gentle": (4, 2),  "Sassy":   (4, 5),  "Careful": (4, 3),  "Quirky":  (-1,-1),
}

def nature_multiplier(nature_name: str, stat_idx: int) -> float:
    """Return 1.1, 0.9, or 1.0 for (nature, stat_idx) pair."""
    info = _NATURE_MODS_CORRECT.get(nature_name, (-1, -1))
    if info[0] == stat_idx:
        return 1.1
    if info[1] == stat_idx:
        return 0.9
    return 1.0


def calc_iv_from_stat(stat_val: int, base: int, level: int,
                       nature_mult: float, is_hp: bool) -> list[int]:
    """
    Return list of possible IVs (0-31) consistent with (stat_val, base, level, nature).
    For HP: stat = floor((2*base + iv) * level / 100) + level + 10
    For others: stat = floor(floor((2*base + iv) * level / 100 + 5) * nature_mult)
    """
    candidates = []
    for iv in range(32):
        if is_hp:
            computed = (2 * base + iv) * level // 100 + level + 10
        else:
            inner = (2 * base + iv) * level // 100 + 5
            computed = int(inner * nature_mult)
        if computed == stat_val:
            candidates.append(iv)
    return candidates


def detect_nature_from_stats(stat_values: list[int], bases: tuple,
                              level: int) -> str | None:
    """
    Derive nature from stat values by trying all 25 natures and checking which
    produces valid IVs (0-31) for every stat.  Works for wild-caught Pokémon
    with 0 EVs.  Returns nature name, or None if ambiguous / no match.
    """
    matches = []
    for nature in NATURES:
        all_valid = True
        for i, (stat_val, base) in enumerate(zip(stat_values, bases)):
            is_hp = (i == 0)
            mult = nature_multiplier(nature, i)
            ivs = calc_iv_from_stat(stat_val, base, level, mult, is_hp)
            if not ivs:
                all_valid = False
                break
        if all_valid:
            matches.append(nature)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Filter out neutral natures if non-neutral matches exist
        non_neutral = [n for n in matches
                       if _NATURE_MODS_CORRECT[n] != (-1, -1)]
        if len(non_neutral) == 1:
            return non_neutral[0]
        log.debug("Multiple natures match stats: %s", matches)
    return None


BASE_STATS = {
    # Name: (HP, Atk, Def, SpA, SpD, Spe)
    "bulbasaur":   (45, 49, 49, 65, 65, 45),
    "charmander":  (39, 52, 43, 60, 50, 65),
    "squirtle":    (44, 48, 65, 50, 64, 43),
    "mewtwo":      (106, 110, 90, 154, 90, 130),
    "zapdos":      (90, 90, 85, 125, 90, 100),
    "articuno":    (90, 85, 100, 95, 125, 85),
    "moltres":     (90, 100, 90, 125, 85, 90),
    "snorlax":     (160, 110, 65, 65, 110, 30),
    "lapras":      (130, 85, 80, 85, 95, 60),
    "porygon":     (65, 60, 70, 75, 75, 40),
    "eevee":       (55, 55, 50, 45, 65, 55),
    "kabuto":      (30, 80, 90, 55, 45, 55),
    "omanyte":     (35, 40, 100, 90, 55, 35),
    "aerodactyl":  (80, 105, 65, 60, 75, 130),
    "ho-oh":       (106, 130, 90, 110, 154, 90),
    "lugia":       (106, 90, 130, 90, 154, 110),
    "deoxys":      (50, 150, 50, 150, 50, 150),
}

# ── PRNG reverse search ───────────────────────────────────────────────────────

def search_pid_reverse(
    tid: int,
    nature_name: str,
    iv_sets: list[list[int]],   # [[hp_ivs], [atk_ivs], [def_ivs], [spa_ivs], [spd_ivs], [spe_ivs]]
) -> list[dict]:
    """
    Reverse-search for PIDs that produce the given Nature + IVs.

    Instead of scanning forward from seed 0 (which fails when the initial seed
    is unknown, e.g. on NSO Switch), this enumerates all possible IV-encoding
    PRNG states and reverses to find the corresponding PID.

    Searches Methods 1, 2, and 4 (VBlank interference variants).
    Returns matching PIDs with SID candidates.
    """
    nature_idx = NATURES.index(nature_name)
    adv = _prng_advance
    rev = _prng_reverse

    # Build all possible r3 values (IV word 1: HP[0:5] | Atk[5:10] | Def[10:15])
    r3_vals = []
    for hp in iv_sets[0]:
        for atk in iv_sets[1]:
            for df in iv_sets[2]:
                r3_vals.append(hp | (atk << 5) | (df << 10))

    # Build set of valid r4 values (IV word 2: SpA[0:5] | SpD[5:10] | Spe[10:15])
    r4_set = set()
    for spa in iv_sets[3]:
        for spd in iv_sets[4]:
            for spe in iv_sets[5]:
                r4_set.add(spa | (spd << 5) | (spe << 10))

    results = []
    seen_pids = set()

    for r3 in r3_vals:
        for lo in range(65536):
            s_iv1 = (r3 << 16) | lo

            # Method 1 & 2: IV2 = advance(IV1) (consecutive)
            s_iv2_consec = adv(s_iv1)
            r4_consec = s_iv2_consec >> 16

            # Method 4: IV2 = advance(advance(IV1)) (one gap)
            s_iv2_gap = adv(s_iv2_consec)
            r4_gap = s_iv2_gap >> 16

            checks = []

            if r4_consec in r4_set:
                # Method 1: seed → PID_low → PID_high → IV1 → IV2
                # PID is 2 reverses from s_iv1
                s2 = rev(s_iv1)
                s1 = rev(s2)
                pid_m1 = ((s2 >> 16) << 16) | (s1 >> 16)
                checks.append(("Method 1", pid_m1, r4_consec))

                # Method 2: seed → PID_low → PID_high → SKIP → IV1 → IV2
                # PID is 3 reverses from s_iv1
                s3 = rev(s_iv1)
                s2 = rev(s3)
                s1 = rev(s2)
                pid_m2 = ((s2 >> 16) << 16) | (s1 >> 16)
                checks.append(("Method 2", pid_m2, r4_consec))

            if r4_gap in r4_set:
                # Method 4: seed → PID_low → PID_high → IV1 → SKIP → IV2
                # PID is 2 reverses from s_iv1
                s2 = rev(s_iv1)
                s1 = rev(s2)
                pid_m4 = ((s2 >> 16) << 16) | (s1 >> 16)
                checks.append(("Method 4", pid_m4, r4_gap))

            for method, pid, r4_actual in checks:
                if pid % 25 != nature_idx:
                    continue
                if pid in seen_pids:
                    continue
                seen_pids.add(pid)

                xor_val = tid ^ (pid >> 16) ^ (pid & 0xFFFF)
                sid_candidates = sorted(set(xor_val ^ x for x in range(8)))

                ivs = [
                    r3 & 0x1F,
                    (r3 >> 5) & 0x1F,
                    (r3 >> 10) & 0x1F,
                    r4_actual & 0x1F,
                    (r4_actual >> 5) & 0x1F,
                    (r4_actual >> 10) & 0x1F,
                ]

                results.append({
                    "method":        method,
                    "pid":           f"{pid:08X}",
                    "ivs":           ivs,
                    "nature":        nature_name,
                    "sid_candidates": sid_candidates,
                })

    return results


# ── OpenCV digit recognition ──────────────────────────────────────────────────
# Hardcoded pixel templates for GBA font digits 0-9 at 7×9 resolution.
# These approximate the Pokémon FRLG number font as displayed on Switch NSO.
# '1' = foreground pixel (white/text), '0' = background pixel.
# Template matching compares each isolated digit blob against all 10 templates
# and picks the best match, so small font variations are tolerated.

_TEMPLATES_7x9 = {
    0: ("0111110",
        "1100011",
        "1000001",
        "1000001",
        "1000001",
        "1000001",
        "1000001",
        "1100011",
        "0111110"),
    1: ("0001000",
        "0011000",
        "0101000",
        "0001000",
        "0001000",
        "0001000",
        "0001000",
        "0001000",
        "0111110"),
    2: ("0111110",
        "1100011",
        "0000001",
        "0000110",
        "0011100",
        "0110000",
        "1100000",
        "1000001",
        "1111111"),
    3: ("0111110",
        "1100011",
        "0000001",
        "0000011",
        "0011110",
        "0000011",
        "0000001",
        "1100011",
        "0111110"),
    4: ("0000110",
        "0001110",
        "0010110",
        "0100110",
        "1000110",
        "1111111",
        "0000110",
        "0000110",
        "0000110"),
    5: ("1111111",
        "1000000",
        "1000000",
        "1111110",
        "0000011",
        "0000001",
        "0000001",
        "1100011",
        "0111110"),
    6: ("0111110",
        "1100011",
        "1000000",
        "1000000",
        "1111110",
        "1000001",
        "1000001",
        "1100011",
        "0111110"),
    7: ("1111111",
        "1000011",
        "0000110",
        "0000100",
        "0001000",
        "0001000",
        "0010000",
        "0010000",
        "0010000"),
    8: ("0111110",
        "1100011",
        "1000001",
        "1100011",
        "0111110",
        "1100011",
        "1000001",
        "1100011",
        "0111110"),
    9: ("0111110",
        "1100011",
        "1000001",
        "1000001",
        "0111111",
        "0000001",
        "0000001",
        "1100011",
        "0111110"),
}

DIGIT_TEMPLATES = {}
for _d, _rows in _TEMPLATES_7x9.items():
    DIGIT_TEMPLATES[_d] = np.array(
        [[int(c) for c in r] for r in _rows], dtype=np.uint8
    )


def _crop_game_area(frame: np.ndarray) -> np.ndarray:
    """Crop black borders if present (Switch screenshots have letterboxing)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return frame
    x, y, w, h = cv2.boundingRect(coords)
    pad = 2
    x, y = max(0, x - pad), max(0, y - pad)
    w = min(frame.shape[1] - x, w + 2 * pad)
    h = min(frame.shape[0] - y, h + 2 * pad)
    cropped = frame[y:y+h, x:x+w]
    # Safety: don't over-crop (e.g., if the whole image is the game)
    if cropped.shape[0] < frame.shape[0] * 0.5:
        return frame
    return cropped


def _isolate_digits(region_bgr: np.ndarray) -> list:
    """
    From a BGR region containing digits, return a list of (x, binary_image)
    tuples sorted left-to-right.  Each binary_image is a tight crop of one
    digit (white-on-black, uint8 0/255).
    """
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)

    # Scale up for better connected-component detection (target ~80px tall)
    h, w = gray.shape
    scale = max(2, 80 // max(h, 1))
    gray = cv2.resize(gray, (w * scale, h * scale),
                      interpolation=cv2.INTER_NEAREST)

    # Threshold — FRLG digits are always darker than background.
    # OTSU alone can miss lighter connecting strokes (e.g., the diagonal
    # in "2"), so we raise the threshold slightly to capture them.
    otsu_val, _ = cv2.threshold(gray, 0, 255,
                                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    thresh = min(otsu_val + 25, gray.mean() - 10)
    _, binary = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY_INV)

    # Bridge small gaps in digit strokes (e.g., split "3" or broken "2")
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    full_h = binary.shape[0]
    min_w = max(3, int(full_h * 0.12))
    digit_items = []
    for i in range(1, num_labels):      # skip background
        bx, by, bw, bh, area = stats[i]
        # Keep components that look like digits: tall enough, wide enough,
        # narrower than tall, and large enough area
        if (bh >= full_h * 0.3 and bw >= min_w and
                bw < bh * 1.5 and area >= max(10, (full_h * 0.08) ** 2)):
            mask = (labels[by:by+bh, bx:bx+bw] == i).astype(np.uint8) * 255
            digit_items.append((bx, mask))

    digit_items.sort(key=lambda d: d[0])
    return digit_items


def _classify_digit(digit_img: np.ndarray) -> tuple:
    """
    Match a single binary digit image against all templates, enhanced with
    structural features (hole counting, aspect ratio) for robustness across
    different fonts and resolutions.
    Returns (digit_int, confidence) or (None, 0.0).
    """
    h, w = digit_img.shape
    if h < 3 or w < 2:
        return (None, 0.0)

    # ── Structural features from original (larger) image ──
    contours, hierarchy = cv2.findContours(
        digit_img.copy(), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    n_holes = 0
    if hierarchy is not None:
        for i in range(len(hierarchy[0])):
            if hierarchy[0][i][3] >= 0:   # child contour = hole
                n_holes += 1

    aspect = w / h

    # Fill distribution
    mid_y, mid_x = h // 2, w // 2
    top_fill = digit_img[:mid_y, :].sum()
    bot_fill = digit_img[mid_y:, :].sum()
    left_fill = digit_img[:, :mid_x].sum()
    right_fill = digit_img[:, mid_x:].sum()

    # ── Template matching on resized image ──
    TMPL_H, TMPL_W = 9, 7
    resized = cv2.resize(digit_img, (TMPL_W, TMPL_H),
                         interpolation=cv2.INTER_AREA)
    candidate = (resized > 127).astype(np.uint8)

    total_px = TMPL_H * TMPL_W
    scores = {}
    for d, tmpl in DIGIT_TEMPLATES.items():
        match_count = int(np.sum(candidate == tmpl))
        scores[d] = match_count / total_px

    # ── Structural adjustments ──
    # 2+ holes → strongly favor 8
    if n_holes >= 2:
        scores[8] += 0.20

    # Very narrow → favor 1
    if aspect < 0.40:
        scores[1] += 0.15
    elif aspect > 0.50:
        scores[1] -= 0.15

    # 1 hole → favor digits known to have holes
    if n_holes == 1:
        for d in (0, 6, 9, 4):
            scores[d] += 0.10
        for d in (1, 2, 3, 5, 7):
            scores[d] -= 0.08

    # 0 holes → penalize digits that should have holes
    if n_holes == 0:
        for d in (0, 8):
            scores[d] -= 0.15
        for d in (6, 9):
            scores[d] -= 0.08

    # Top-heavy / bottom-heavy hints
    total = max(top_fill + bot_fill, 1)
    top_frac = top_fill / total
    if top_frac > 0.60:     # more ink on top → could be 7, 9
        scores[7] += 0.05
        scores[9] += 0.03
    elif top_frac < 0.40:   # more ink on bottom → could be 6
        scores[6] += 0.05

    # Quadrant fill analysis — distinguishes Z/S shapes (2, 5) from 7
    q_tl = digit_img[:mid_y, :mid_x].mean() / 255.0 if mid_y > 0 and mid_x > 0 else 0
    q_tr = digit_img[:mid_y, mid_x:].mean() / 255.0 if mid_y > 0 else 0
    q_bl = digit_img[mid_y:, :mid_x].mean() / 255.0 if mid_x > 0 else 0
    q_br = digit_img[mid_y:, mid_x:].mean() / 255.0
    # Z/S pattern: fill in top-left + bottom-right, empty in top-right + bottom-left
    z_score = (q_tl + q_br) - (q_tr + q_bl)
    if z_score > 0.25:
        scores[5] += 0.15
        scores[2] += 0.10
        scores[7] -= 0.12
    elif z_score < -0.25:
        # Reverse Z pattern (top-right + bottom-left): favors 2 over 5
        scores[2] += 0.15
        scores[5] -= 0.10

    best_digit = max(scores, key=scores.get)
    best_score = min(scores[best_digit], 1.0)

    return (best_digit, best_score)


def read_digits(region_bgr: np.ndarray, min_confidence: float = 0.55) -> str:
    """
    Read digits from a BGR image region using OpenCV template matching.
    Returns the digits as a string, or empty string if none found.
    """
    digit_items = _isolate_digits(region_bgr)

    result = ""
    for _, digit_img in digit_items:
        d, conf = _classify_digit(digit_img)
        if d is not None and conf >= min_confidence:
            result += str(d)

    return result


def _crop_region(frame: np.ndarray, rel: tuple) -> np.ndarray:
    """Crop a relative region (top, left, bottom, right) from frame."""
    h, w = frame.shape[:2]
    y1, x1, y2, x2 = int(rel[0]*h), int(rel[1]*w), int(rel[2]*h), int(rel[3]*w)
    return frame[y1:y2, x1:x2]


def _read_region_digits(frame: np.ndarray, rel: tuple) -> str:
    """Crop a region and read digits from it."""
    crop = _crop_region(frame, rel)
    return read_digits(crop)


# ── Nature detection from stat color tints ────────────────────────────────────

# In FRLG, the boosted stat name is tinted RED (more reddish) and
# the lowered stat name is tinted BLUE on the Stats summary page.
# Stat label positions on the FRLG Stats summary page (relative to frame):
#   Labels appear on the LEFT side of the stat values.
#   Order on screen: HP / Attack / Defense / Sp.Atk / Sp.Def / Speed

# Approximate positions for each stat LABEL (left column of the stats page).
# These are tuned for FRLG NSO on Switch displayed at 640x480 via OBS.
# (top, left, bottom, right) — fractions of frame size.
STAT_LABEL_REGIONS = {
    "hp":    (0.13, 0.50, 0.20, 0.70),
    "atk":   (0.25, 0.50, 0.31, 0.78),
    "def":   (0.33, 0.50, 0.39, 0.78),
    "spa":   (0.41, 0.50, 0.48, 0.78),
    "spd":   (0.49, 0.50, 0.56, 0.78),
    "spe":   (0.57, 0.50, 0.64, 0.78),
}

# Approximate positions for each stat VALUE (right column).
STAT_VALUE_REGIONS = {
    "hp":    (0.13, 0.90, 0.20, 0.99),
    "atk":   (0.25, 0.90, 0.31, 0.99),
    "def":   (0.33, 0.90, 0.39, 0.99),
    "spa":   (0.41, 0.90, 0.48, 0.99),
    "spd":   (0.49, 0.90, 0.56, 0.99),
    "spe":   (0.57, 0.90, 0.64, 0.99),
}

# TID region on the Trainer Card screen (top, left, bottom, right).
# Covers the 5-digit ID number after "IDNo." in the top-right header area.
TRAINER_CARD_TID_REGION = (0.10, 0.73, 0.19, 0.86)


def _mean_color_in_region(frame: np.ndarray, rel: tuple) -> np.ndarray:
    """Return mean BGR color in a relative region."""
    h, w = frame.shape[:2]
    y1, x1, y2, x2 = int(rel[0]*h), int(rel[1]*w), int(rel[2]*h), int(rel[3]*w)
    crop = frame[y1:y2, x1:x2]
    return crop.mean(axis=(0, 1))  # [B, G, R]


def detect_nature_from_colors(frame: np.ndarray) -> str | None:
    """
    Examine the mean color of each stat label region.
    Red tint (R higher than B,G) → boosted stat.
    Blue tint (B higher than R,G) → lowered stat.
    Returns the detected nature name, or None if ambiguous.
    """
    stat_order = ["hp", "atk", "def", "spa", "spd", "spe"]
    stat_idx    = {"hp": 0, "atk": 1, "def": 2, "spa": 3, "spd": 4, "spe": 5}

    colors = {}
    for stat, reg in STAT_LABEL_REGIONS.items():
        colors[stat] = _mean_color_in_region(frame, reg)  # [B, G, R]

    # Red score: R - max(B, G)
    red_score  = {s: c[2] - max(c[0], c[1]) for s, c in colors.items()}
    # Blue score: B - max(R, G)
    blue_score = {s: c[0] - max(c[1], c[2]) for s, c in colors.items()}

    boosted_stat = max(red_score, key=red_score.get)
    lowered_stat = max(blue_score, key=blue_score.get)

    # Threshold: only report if the color deviation is significant
    THRESHOLD = 10
    boosted_idx = stat_idx[boosted_stat] if red_score[boosted_stat]  > THRESHOLD else -1
    lowered_idx = stat_idx[lowered_stat] if blue_score[lowered_stat] > THRESHOLD else -1

    # Find the nature matching (boosted_idx, lowered_idx)
    for name, (b, l) in _NATURE_MODS_CORRECT.items():
        if b == boosted_idx and l == lowered_idx:
            return name

    return None


# ── Camera helpers ────────────────────────────────────────────────────────────

def _open_camera(device_index: int) -> CaptureHandler:
    cap = CaptureHandler(device_index=device_index)
    cap.open()
    return cap


def _grab_stable_frame(cap: CaptureHandler, samples: int = 5) -> np.ndarray | None:
    """Grab a few frames and return the last non-None one."""
    frame = None
    for _ in range(samples):
        f = cap.grab_frame()
        if f is not None:
            frame = f
        time.sleep(0.05)
    return frame


def _save_debug(frame: np.ndarray, name: str, debug_dir: str):
    os.makedirs(debug_dir, exist_ok=True)
    path = os.path.join(debug_dir, name)
    cv2.imwrite(path, frame)
    log.info(f"[debug] Saved {path}")


# ── Main flow ─────────────────────────────────────────────────────────────────

def _get_frame_from_source(
    screenshot_path: str | None,
    cap: CaptureHandler | None,
    prompt_msg: str,
    debug_dir: str | None,
    debug_name: str,
) -> np.ndarray:
    """
    Return a frame from either a screenshot file or a live camera feed.
    Raises SystemExit if neither source can provide an image.
    """
    if screenshot_path:
        frame = cv2.imread(screenshot_path)
        if frame is None:
            print(f"\n  ERROR: Cannot read image file: {screenshot_path}")
            sys.exit(1)
        print(f"  Loaded screenshot: {screenshot_path}")
    elif cap is not None:
        print(prompt_msg)
        input("  Press ENTER when ready...")
        frame = _grab_stable_frame(cap)
        if frame is None:
            log.error("Could not grab frame from camera.")
            sys.exit(1)
    else:
        print("\n  ERROR: No image source — provide a screenshot path or use --device for camera.")
        sys.exit(1)

    if debug_dir:
        _save_debug(frame, debug_name, debug_dir)
    return frame


def _prompt_tid_manual() -> int:
    """Ask user to type their TID."""
    return int(input("  Enter your TID (5-digit number on Trainer Card): ").strip())


def _prompt_nature_manual() -> str:
    """Interactive nature picker."""
    print("\n  Available natures:")
    for i, n in enumerate(NATURES):
        print(f"    {i:2d}. {n}")
    idx = int(input("  Enter nature number: ").strip())
    return NATURES[idx]


def _prompt_stats_manual(species: str, level: int) -> list[int]:
    """Ask user to type all 6 stat values."""
    labels = ["HP", "Attack", "Defense", "Sp.Atk", "Sp.Def", "Speed"]
    print(f"\n  Enter stats for {species.title()} (Level {level}):")
    vals = []
    for label in labels:
        vals.append(int(input(f"    {label}: ").strip()))
    return vals


def read_tid_from_frame(frame: np.ndarray) -> str:
    """Read TID from a Trainer Card frame using OpenCV digit recognition."""
    game = _crop_game_area(frame)
    return _read_region_digits(game, TRAINER_CARD_TID_REGION)


def read_stats_and_nature_from_frame(frame: np.ndarray) -> tuple:
    """
    Read stats and nature from a Skills page frame.
    Returns (nature_name_or_None, {"hp": "236", "atk": "163", ...}).
    """
    game = _crop_game_area(frame)

    nature = detect_nature_from_colors(game)

    stat_order = ["hp", "atk", "def", "spa", "spd", "spe"]
    auto_stats = {}
    for stat in stat_order:
        val_str = _read_region_digits(game, STAT_VALUE_REGIONS[stat])
        # HP region may contain "current/max" — take last ≤3 digits
        if stat == "hp" and len(val_str) > 3:
            val_str = val_str[-3:]
        auto_stats[stat] = val_str

    return nature, auto_stats


def run_sid_search(
    tid: int,
    nature: str,
    iv_candidates: list[list[int]],
    is_shiny: bool,
    mode: str,
) -> list[dict]:
    print("\n" + "="*60)
    print("  Searching for matching PIDs (reverse PRNG)...")
    print("="*60)

    # Count search space
    n_r3 = 1
    for s in iv_candidates[:3]:
        n_r3 *= len(s)
    n_r4 = 1
    for s in iv_candidates[3:]:
        n_r4 *= len(s)
    total = n_r3 * 65536
    print(f"  TID={tid}, Nature={nature}, IsShiny={is_shiny}")
    print(f"  IV word combos: {n_r3} × {n_r4}, search iterations: {total:,}")
    print(f"  Checking Methods 1, 2, and 4...")

    results = search_pid_reverse(
        tid=tid,
        nature_name=nature,
        iv_sets=iv_candidates,
    )

    return results


def print_results(results: list[dict], tid: int, species: str, is_shiny: bool):
    print("\n" + "="*60)
    print("  RESULTS")
    print("="*60)

    if not results:
        print("\n  ✗ No matching PIDs found.")
        print("\n  Possible causes:")
        print("  • Stats were read/entered incorrectly — try again.")
        print("  • Nature was misidentified.")
        print("  • The Pokémon has EVs (only works on freshly-caught with 0 EVs).")
        return

    print(f"\n  Found {len(results)} matching PID(s):\n")
    for r in results:
        ivs = r["ivs"]
        print(f"  {r['method']:>8}  PID={r['pid']}  Nature={r['nature']}")
        print(f"           IVs: HP={ivs[0]} Atk={ivs[1]} Def={ivs[2]} SpA={ivs[3]} SpD={ivs[4]} Spe={ivs[5]}")
        if is_shiny:
            print(f"           SID candidates (one of these is your real SID):")
            for sid in r["sid_candidates"]:
                print(f"             SID={sid:05d}  (TID={tid:05d})")
        else:
            print(f"           Closest shiny SIDs (for reference):")
            for sid in r["sid_candidates"]:
                print(f"             SID={sid:05d}")
        print()

    if len(results) == 1:
        best = results[0]
        print("  → Single match found — this is almost certainly correct.")
        if is_shiny:
            print(f"  → Your SID is one of: {best['sid_candidates']}")
            print(f"  → Most likely SID:    {best['sid_candidates'][0]}")
    elif len(results) <= 5:
        print(f"  → Multiple matches. Narrow down by catching another Pokémon")
        print(f"     and running this tool again with that Pokémon's stats.")
    else:
        print(f"  → Too many matches ({len(results)}). Stats may be partially incorrect,")
        print(f"     or EVs may not be 0. Only works on freshly-caught/received Pokémon.")


def save_profile(tid: int, sid: int, profile_path: str):
    profile = {}
    if os.path.exists(profile_path):
        with open(profile_path) as f:
            try:
                profile = json.load(f)
            except Exception:
                pass
    profile["tid"] = tid
    profile["sid"] = sid
    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)
    print(f"\n  Saved TID={tid}, SID={sid} to {profile_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SID Finder for FRLG (Switch NSO) — OpenCV only, no Tesseract needed."
    )

    # Basic info
    parser.add_argument(
        "--species", required=True,
        help="Pokémon species (e.g. mewtwo, bulbasaur, ho-oh)"
    )
    parser.add_argument(
        "--mode", choices=["starter", "legendary"], default="legendary",
        help="starter = early game (frame 0-3000); legendary = caught later (0-60000)"
    )
    parser.add_argument(
        "--level", type=int, default=None,
        help="Level of the Pokémon (auto-detected from species if omitted)"
    )
    parser.add_argument(
        "--shiny", action="store_true",
        help="The Pokémon IS shiny (needed for SID extraction from shiny PID)"
    )

    # Input sources — screenshots
    parser.add_argument(
        "--screenshot-tid", default=None, metavar="PATH",
        help="Path to a Trainer Card screenshot (for reading TID)"
    )
    parser.add_argument(
        "--screenshot-stats", default=None, metavar="PATH",
        help="Path to a Pokémon Skills/Stats page screenshot (for reading stats)"
    )

    # Input sources — manual overrides
    parser.add_argument(
        "--tid", type=int, default=None,
        help="Trainer ID (skip TID reading if you already know it)"
    )
    parser.add_argument(
        "--nature", default=None,
        help="Nature name, e.g. Impish (skip auto-detection)"
    )

    # Input source — camera
    parser.add_argument(
        "--device", type=int, default=None,
        help="OBS Virtual Camera device index for live mode (e.g. 3)"
    )

    # Output
    parser.add_argument(
        "--save", action="store_true",
        help="Save found TID/SID to data/hunt_profile.json"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Save debug images to tools/screenshots/sid_debug/"
    )

    args = parser.parse_args()

    species = args.species.lower()
    if species not in BASE_STATS:
        print(f"Unknown species '{species}'. Available: {', '.join(sorted(BASE_STATS.keys()))}")
        sys.exit(1)

    default_levels = {
        "bulbasaur": 5, "charmander": 5, "squirtle": 5,
        "mewtwo": 70, "zapdos": 50, "articuno": 50, "moltres": 50,
        "snorlax": 30, "lapras": 25, "porygon": 25, "eevee": 25,
        "kabuto": 5, "omanyte": 5, "aerodactyl": 5,
        "ho-oh": 70, "lugia": 70, "deoxys": 30,
    }
    level = args.level or default_levels.get(species, 5)
    is_shiny = args.shiny or (args.mode == "legendary")

    debug_dir = None
    if args.debug:
        base = os.path.dirname(os.path.abspath(__file__))
        debug_dir = os.path.join(base, "screenshots", "sid_debug")

    # ── Header ──
    print("\n" + "="*60)
    print("  FRLG SID FINDER (OpenCV — no Tesseract needed)")
    print("="*60)
    print(f"  Species: {species.title()} (Level {level})")
    print(f"  Shiny:   {is_shiny}")
    print(f"  Mode:    {args.mode}")
    print()

    # Open camera only if needed and requested
    cap = None
    need_camera = (args.device is not None and
                   (args.tid is None and args.screenshot_tid is None) or
                   (args.screenshot_stats is None and args.nature is None))
    if args.device is not None and need_camera:
        print(f"  Opening camera (device {args.device})...")
        try:
            cap = _open_camera(args.device)
        except RuntimeError as e:
            print(f"  WARNING: Camera failed: {e}")
            print("  Falling back to manual entry.")

    try:
        # ── STEP 1: Get TID ──
        print("\n" + "-"*60)
        print("  STEP 1 — Trainer ID")
        print("-"*60)

        tid = args.tid
        if tid is None:
            # Try screenshot or camera
            if args.screenshot_tid or cap is not None:
                frame_tid = _get_frame_from_source(
                    args.screenshot_tid, cap,
                    "  Navigate to Trainer Card screen.",
                    debug_dir, "trainer_card.png",
                )
                tid_str = read_tid_from_frame(frame_tid)
                if tid_str:
                    print(f"\n  TID auto-read: {tid_str}")
                    confirm = input("  Is this correct? (y/n): ").strip().lower()
                    if confirm == "y":
                        tid = int(tid_str)
                if tid is None:
                    print("  Could not read TID automatically.")
                    tid = _prompt_tid_manual()
            else:
                tid = _prompt_tid_manual()

        print(f"\n  ✓ TID = {tid}")

        # ── STEP 2: Get Nature + Stats ──
        print("\n" + "-"*60)
        print("  STEP 2 — Nature & Stats")
        print("-"*60)

        nature = args.nature
        stat_values = None

        if args.screenshot_stats or cap is not None:
            frame_stats = _get_frame_from_source(
                args.screenshot_stats, cap,
                f"  Navigate to {species.title()}'s Skills/Stats page.",
                debug_dir, "stats_page.png",
            )

            # Auto-read stat values
            _, auto_stats = read_stats_and_nature_from_frame(frame_stats)
            stat_order = ["hp", "atk", "def", "spa", "spd", "spe"]
            labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]

            stat_values = []
            print(f"\n  Reading stats for {species.title()} (Level {level}):")
            for stat, label in zip(stat_order, labels):
                val_str = auto_stats[stat]
                if val_str:
                    val = int(val_str)
                    print(f"    {label:<4}: {val}")
                    stat_values.append(val)
                else:
                    val = int(input(f"    Could not read {label}. Enter manually: ").strip())
                    stat_values.append(val)

            # Confirm stats
            print("\n  Stats summary:")
            for label, val in zip(labels, stat_values):
                print(f"    {label}: {val}")
            confirm = input("\n  Are these correct? (y/n): ").strip().lower()
            if confirm != "y":
                print("  Enter corrected values (ENTER to keep current):")
                for i, (label, cur) in enumerate(zip(labels, stat_values)):
                    raw = input(f"    {label} [{cur}]: ").strip()
                    if raw:
                        stat_values[i] = int(raw)

            # Auto-detect nature from confirmed stat values
            if nature is None:
                bases = BASE_STATS[species]
                auto_nature = detect_nature_from_stats(stat_values, bases, level)
                if auto_nature:
                    print(f"\n  Nature detected from stats: {auto_nature}")
                    confirm = input("  Is this correct? (y/n): ").strip().lower()
                    if confirm == "y":
                        nature = auto_nature

        # Fallback: fully manual stat entry
        if stat_values is None:
            stat_values = _prompt_stats_manual(species, level)

        # Derive nature from stats if not yet known
        if nature is None:
            bases = BASE_STATS[species]
            auto_nature = detect_nature_from_stats(stat_values, bases, level)
            if auto_nature:
                print(f"\n  Nature detected from stats: {auto_nature}")
                confirm = input("  Is this correct? (y/n): ").strip().lower()
                if confirm == "y":
                    nature = auto_nature

        # Fallback: manual nature entry
        if nature is None:
            nature = _prompt_nature_manual()

        print(f"\n  ✓ Nature = {nature}")

        # ── STEP 3: Calculate IVs ──
        print("\n" + "-"*60)
        print("  STEP 3 — IV Calculation")
        print("-"*60)

        bases = BASE_STATS[species]
        labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
        iv_candidates = []
        for i, (stat_val, base, label) in enumerate(zip(stat_values, bases, labels)):
            is_hp = (i == 0)
            nat_mult = nature_multiplier(nature, i)
            ivs = calc_iv_from_stat(stat_val, base, level, nat_mult, is_hp)
            if not ivs:
                print(f"  ⚠ No valid IV for {label} (stat={stat_val}, base={base}, "
                      f"lv={level}, mult={nat_mult})")
                print(f"    Assuming IV range 0-31 (more candidates, slower search).")
                ivs = list(range(32))
            else:
                print(f"  {label}: {ivs}")
            iv_candidates.append(ivs)

        # ── STEP 4: PRNG search ──
        results = run_sid_search(tid, nature, iv_candidates, is_shiny, args.mode)

        # ── STEP 5: Results ──
        print_results(results, tid, species, is_shiny)

        # ── Save profile ──
        if args.save and results:
            best = results[0]
            sid_to_save = best["sid_candidates"][0]
            if len(results) == 1 and len(best["sid_candidates"]) <= 8:
                sid_input = input(
                    f"\n  Which SID to save? (default={sid_to_save}): "
                ).strip()
                if sid_input:
                    sid_to_save = int(sid_input)
            profile_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "data", "hunt_profile.json"
            )
            save_profile(tid, sid_to_save, profile_path)

    finally:
        if cap is not None:
            cap.close()


if __name__ == "__main__":
    main()
