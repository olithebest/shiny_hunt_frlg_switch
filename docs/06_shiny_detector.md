# `src/detection/shiny_detector.py` — Documentation

## Purpose

Determines whether the Pokémon appearing on screen is shiny.
Uses a three-tier detection system, tried in priority order.

---

## Detection Tiers (in priority order)

### Tier 1 — Reference Image Comparison (most robust)
Compares the live sprite's HSV histogram against saved reference screenshots.

- If **both** `data/reference_shinies/{target}_shiny.png` and
  `data/reference_normals/{target}_normal.png` exist:
  → Scores the live frame against both references. Declares shiny if it's
  closer to the shiny reference. Handles very subtle color differences (e.g. Snorlax).

- If **only** the shiny reference exists:
  → Declares shiny if similarity score ≥ `reference_match_threshold` (default 0.70).

### Tier 2 — HSV Color Range Fallback
Uses hand-tuned HSV ranges from `shiny_colors.py` to count shiny-colored
pixels in the sprite region. Used when no reference images exist.

### Tier 3 — Sparkle Pixel Counting (last resort)
Counts white/yellow sparkle-colored pixels during the battle intro animation.
Least reliable — sparkle colors vary by background.

---

## `ShinyDetectionResult`

Data class returned by all detection methods.

| Field | Type | Meaning |
|-------|------|---------|
| `is_shiny` | `bool` | Final verdict |
| `confidence` | `float` | 0.0–1.0 score from comparison |
| `frame` | `np.ndarray` | The frame used for detection |
| `sparkle_triggered` | `bool` | Whether sparkle counting was the deciding factor |
| `color_confirmed` | `bool \| None` | Result of HSV color check; `None` if not attempted |

---

## Class: `ShinyDetector`

### Constructor
```python
ShinyDetector(threshold: int = SPARKLE_PIXEL_THRESHOLD)
```
- `threshold` — minimum sparkle pixel count for Tier 3 detection.
  Imported from `shiny_colors.py`.

---

### `_get_cached_sprite_crop(target, shiny=True) -> np.ndarray | None`
Loads the reference image for `target` (e.g. `"mewtwo"`), crops the sprite
region using `POKEMON_SPRITE_REGION`, runs `_auto_find_sprite()` to isolate
the Pokémon body, and caches the 128×128 result.

Cache key format: `"shiny_sprite_mewtwo"` or `"normal_sprite_mewtwo"`.

Reference image paths:
```
data/reference_shinies/mewtwo_shiny.png
data/reference_normals/mewtwo_normal.png
```

---

### `_auto_find_sprite(crop) -> np.ndarray`
Detects the Pokémon sprite within a cropped region by finding the largest
contiguous non-background blob. Returns a tight bounding-box crop resized to 128×128.

---

### `_compare_histograms(frame_crop, ref_crop) -> float`
Computes the correlation between HSV histograms of the live frame crop and
a reference crop. Returns a score between -1.0 and 1.0 (1.0 = identical).

Uses `cv2.calcHist()` over Hue (50 bins) and Saturation (60 bins), normalized,
then `cv2.compareHist()` with `cv2.HISTCMP_CORREL`.

---

### `check(frame, target) -> ShinyDetectionResult`
Main public method. Runs all three detection tiers in order and returns
a `ShinyDetectionResult`.

**Parameters:**
- `frame` — BGR numpy array from `CaptureHandler.grab_frame()`
- `target` — hunt target string, e.g. `"mewtwo"`

**Flow:**
```
1. Crop sprite region from frame using POKEMON_SPRITE_REGION
2. If reference images exist for target:
   a. Load/retrieve cached shiny reference crop
   b. Compare histograms → shiny_score
   c. If normal reference also exists:
      - Compare against normal → normal_score
      - is_shiny = shiny_score > normal_score
      - confidence = shiny_score - normal_score (margin)
   d. Else: is_shiny = shiny_score >= threshold (0.70)
3. If no reference images: HSV color count fallback
4. If no color profile: sparkle pixel counting
5. Return ShinyDetectionResult
```

---

## Supporting Files

### `shiny_colors.py`
Defines:
- `SPARKLE_STAR_COLORS` — HSV ranges for sparkle pixels
- `SPARKLE_PIXEL_THRESHOLD` — minimum sparkle pixels for Tier 3
- `BATTLE_REGION` — `(top, left, bottom, right)` fractions for the full battle area
- `POKEMON_SPRITE_REGION` — fractions for the enemy Pokémon sprite area
- `POKEMON_BODY_COLORS` — per-target HSV color ranges for Tier 2 fallback

### `frlg_palettes.py`
Provides:
- `get_palette(target)` — returns the known FRLG battle palette for a target
- `classify_hue(hue)` — bins an HSV hue value into a color name
- `PaletteEntry` — named tuple for palette entries

Used in diagnostic tools (`tools/analyze_hue.py`) to build reference data.

---

## Adding a New Hunt Target

1. Take a screenshot of the target in battle on the normal encounter
   → save as `data/reference_normals/{target}_normal.png`
2. Take a screenshot of the shiny version
   → save as `data/reference_shinies/{target}_shiny.png`
3. Add the target to `HUNT_CATALOGUE` in `license_manager.py`
4. Add a hunt sequence in `sequences.py`
5. Run `tools/test_hooh_detection.py` (adapted) to verify detection accuracy
