import cv2
import numpy as np
import os
import logging
from typing import Optional, List, Dict

from .shiny_colors import SPARKLE_STAR_COLORS, SPARKLE_PIXEL_THRESHOLD, BATTLE_REGION, POKEMON_SPRITE_REGION, POKEMON_BODY_COLORS
from .frlg_palettes import get_palette, classify_hue, PaletteEntry

logger = logging.getLogger(__name__)

# data/reference_shinies/{target}_shiny.png  — screenshot of the shiny Pokemon in battle
REFERENCE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "reference_shinies")
# data/reference_normals/{target}_normal.png — screenshot of the NORMAL Pokemon in battle
# Optional but recommended for targets with subtle shiny differences (e.g. Snorlax).
# When present, detection picks whichever reference the live frame is closer to.
NORMAL_REFERENCE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "reference_normals")


class ShinyDetectionResult:
    def __init__(
        self,
        is_shiny: bool,
        confidence: float,
        frame: Optional[np.ndarray] = None,
        sparkle_triggered: bool = False,
        color_confirmed: Optional[bool] = None,  # None = no color check done
    ):
        self.is_shiny = is_shiny
        self.confidence = confidence
        self.frame = frame
        self.sparkle_triggered = sparkle_triggered
        self.color_confirmed = color_confirmed

    def __repr__(self):
        return (
            f"ShinyDetectionResult(is_shiny={self.is_shiny}, "
            f"confidence={self.confidence:.2f}, "
            f"sparkle={self.sparkle_triggered}, "
            f"color_confirmed={self.color_confirmed})"
        )


class ShinyDetector:
    """
    Three-tier shiny detection for FRLG, tried in order:

    1. Reference image comparison (most robust):
         Crops the enemy sprite from the live frame and compares its hue+saturation
         histogram against a reference battle screenshot.
         - If data/reference_shinies/{target}_shiny.png AND
              data/reference_normals/{target}_normal.png both exist:
               → picks whichever the live frame is closer to. Handles subtle shinies.
         - If only the shiny reference exists:
               → declares shiny if similarity score >= reference_match_threshold (default 0.70).

    2. HSV color range fallback:
         Used when no reference images exist yet for the target.
         Counts shiny-colored pixels in the sprite region.

    3. Sparkle pixel counting (last resort):
         Used when neither reference images nor a color profile exist.
    """

    def __init__(self, threshold: int = SPARKLE_PIXEL_THRESHOLD):
        self.threshold = threshold
        self._ref_cache: Dict[str, Optional[np.ndarray]] = {}

    def _get_cached_sprite_crop(self, target: str, shiny: bool = True) -> Optional[np.ndarray]:
        """
        Load the reference image (shiny or normal), crop the sprite region using
        POKEMON_SPRITE_REGION (same as live frames), run _auto_find_sprite, and
        cache the 128x128 result for the rest of the session.

        Reference images:
          data/reference_shinies/{target}_shiny.png
          data/reference_normals/{target}_normal.png
        """
        cache_key = f"{'shiny' if shiny else 'normal'}_sprite_{target}"
        if cache_key in self._ref_cache:
            return self._ref_cache[cache_key]

        ref_dir = REFERENCE_DIR if shiny else NORMAL_REFERENCE_DIR
        suffix  = "shiny" if shiny else "normal"
        path = os.path.normpath(os.path.join(ref_dir, f"{target}_{suffix}.png"))

        if not os.path.isfile(path):
            self._ref_cache[cache_key] = None
            return None

        img = cv2.imread(path)
        sprite = self._auto_find_sprite(
            img,
            search_region=(
                POKEMON_SPRITE_REGION["top"],
                POKEMON_SPRITE_REGION["left"],
                POKEMON_SPRITE_REGION["bottom"],
                POKEMON_SPRITE_REGION["right"],
            )
        )
        logger.info(f"Cached {suffix} reference sprite for {target} from {path}")
        self._ref_cache[cache_key] = sprite
        return sprite

    def _hs_histogram(self, img: np.ndarray) -> np.ndarray:
        """Combined hue+saturation histogram of an image, normalised."""
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h_hist = cv2.calcHist([hsv], [0], None, [180], [0, 180])
        s_hist = cv2.calcHist([hsv], [1], None, [256], [0, 256])
        combined = np.concatenate([h_hist, s_hist])
        cv2.normalize(combined, combined)
        return combined

    def _histogram_similarity(self, img_a: np.ndarray, img_b: np.ndarray) -> float:
        """
        Compare two sprite images by their combined hue+saturation histogram.
        Returns correlation: 1.0 = identical color distribution, -1.0 = opposite.
        Ignores brightness so capture card exposure differences don't matter.
        """
        return float(cv2.compareHist(self._hs_histogram(img_a), self._hs_histogram(img_b), cv2.HISTCMP_CORREL))

    def confirm_shiny_by_reference(self, frame: np.ndarray, target: str) -> Optional[bool]:
        """
        Compare the live sprite histogram against reference shiny (and optionally normal)
        images to decide if the encounter is shiny.

        - Both shiny + normal references exist:
            Picks whichever the live frame is closer to.
            Best for subtle shinies (e.g. Snorlax) where color ranges overlap.
        - Only shiny reference exists:
            Returns True if similarity >= reference_match_threshold (default 0.70).
        - No shiny reference:
            Returns None — caller falls back to HSV color ranges.
        """
        shiny_sprite = self._get_cached_sprite_crop(target, shiny=True)
        if shiny_sprite is None:
            return None

        live_sprite = self._auto_find_sprite(
            frame,
            search_region=(
                POKEMON_SPRITE_REGION["top"],
                POKEMON_SPRITE_REGION["left"],
                POKEMON_SPRITE_REGION["bottom"],
                POKEMON_SPRITE_REGION["right"],
            )
        )

        score_shiny = self._histogram_similarity(live_sprite, shiny_sprite)

        normal_sprite = self._get_cached_sprite_crop(target, shiny=False)
        if normal_sprite is not None:
            score_normal = self._histogram_similarity(live_sprite, normal_sprite)
            verdict = score_shiny > score_normal
            logger.info(
                f"[ref check] {target}: vs_shiny={score_shiny:.3f}, vs_normal={score_normal:.3f}"
                f" → {'SHINY' if verdict else 'normal'}"
            )
            return verdict

        # Only shiny reference — use configurable threshold
        color_profile = POKEMON_BODY_COLORS.get(target.lower(), {})
        threshold = color_profile.get("reference_match_threshold", 0.70)
        verdict = score_shiny >= threshold
        logger.info(
            f"[ref check] {target}: vs_shiny={score_shiny:.3f}, threshold={threshold:.2f}"
            f" → {'SHINY' if verdict else 'normal'}"
        )
        return verdict

    def _auto_find_sprite(self, image: np.ndarray, search_region: Optional[tuple] = None) -> np.ndarray:
        """
        Automatically locate the Pokemon sprite within an image and return
        a 128x128 crop of it.

        Works on any source — live capture, internet screenshot, etc.
        Strategy:
          1. If a search_region (top, left, bottom, right) fraction is given, crop there first
          2. Convert to grayscale, apply edge detection
          3. Find the largest contiguous non-trivial region (the Pokemon body)
          4. Get its bounding box, pad slightly, crop and resize to 128x128

        If no clear contour is found, falls back to the full search region resized.
        """
        h, w = image.shape[:2]
        if search_region:
            t = int(search_region[0] * h)
            l = int(search_region[1] * w)
            b = int(search_region[2] * h)
            r = int(search_region[3] * w)
            region = image[t:b, l:r]
        else:
            region = image.copy()

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

        # Blur + Canny to find edges of the sprite silhouette
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges   = cv2.Canny(blurred, 30, 100)

        # Dilate to connect nearby edges into solid blobs
        kernel  = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            # Take the largest contour — that's the Pokemon
            largest = max(contours, key=cv2.contourArea)
            x, y, cw, ch = cv2.boundingRect(largest)

            # Add 10% padding
            pad_x = max(int(cw * 0.10), 4)
            pad_y = max(int(ch * 0.10), 4)
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(region.shape[1], x + cw + pad_x)
            y2 = min(region.shape[0], y + ch + pad_y)

            sprite = region[y1:y2, x1:x2]
        else:
            sprite = region  # fallback: use full search region

        if sprite.size == 0:
            sprite = region

        return cv2.resize(sprite, (128, 128))

    # ------------------------------------------------------------------
    # Stage 1: sparkle pixel counting
    # ------------------------------------------------------------------

    def _get_battle_region(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        top    = int(BATTLE_REGION["top"]    * h)
        left   = int(BATTLE_REGION["left"]   * w)
        bottom = int(BATTLE_REGION["bottom"] * h)
        right  = int(BATTLE_REGION["right"]  * w)
        return frame[top:bottom, left:right]

    def _count_sparkle_pixels(self, frame: np.ndarray) -> int:
        region = self._get_battle_region(frame)
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        total = 0
        for ranges in SPARKLE_STAR_COLORS.values():
            mask = cv2.inRange(hsv, ranges["lower"], ranges["upper"])
            total += cv2.countNonZero(mask)
        return total

    def check_frame(self, frame: np.ndarray) -> ShinyDetectionResult:
        """Check a single frame for shiny sparkle pixels (Stage 1 only)."""
        count = self._count_sparkle_pixels(frame)
        confidence = min(count / max(self.threshold * 3, 1), 1.0)
        return ShinyDetectionResult(
            is_shiny=count >= self.threshold,
            confidence=confidence,
            frame=frame.copy(),
            sparkle_triggered=count >= self.threshold,
        )

    # ------------------------------------------------------------------
    # Universal sparkle detection via frame differencing
    # ------------------------------------------------------------------

    def detect_sparkle_animation(self, frames: List[np.ndarray]) -> bool:
        """
        Detect shiny sparkle stars by looking for bright pixels that APPEAR
        between consecutive frames.  Works for ALL Pokemon — no species data needed.

        Gen 3 shiny sparkles are bright white/yellow star shapes that flash in
        and out over ~0.5 seconds.  We detect them as newly-appeared bright pixels
        in frame-to-frame differences within the battle region.

        Returns True if sparkle animation pattern is detected.
        """
        if len(frames) < 4:
            return False

        sparkle_scores = []
        for i in range(1, len(frames)):
            prev_region = self._get_battle_region(frames[i - 1])
            curr_region = self._get_battle_region(frames[i])

            if prev_region.shape != curr_region.shape:
                continue

            # Find pixels that are very bright NOW but were NOT bright before.
            # Sparkle stars are near-white (high value, low saturation).
            hsv_curr = cv2.cvtColor(curr_region, cv2.COLOR_BGR2HSV)
            hsv_prev = cv2.cvtColor(prev_region, cv2.COLOR_BGR2HSV)

            # Bright, low-saturation pixels (white/near-white sparkle stars)
            bright_curr = cv2.inRange(hsv_curr, np.array([0, 0, 210]), np.array([180, 60, 255]))
            bright_prev = cv2.inRange(hsv_prev, np.array([0, 0, 210]), np.array([180, 60, 255]))
            new_bright = cv2.bitwise_and(bright_curr, cv2.bitwise_not(bright_prev))

            # Also detect saturated sparkle colors (yellow, blue, pink star tips)
            for color_name, ranges in SPARKLE_STAR_COLORS.items():
                color_curr = cv2.inRange(hsv_curr, ranges["lower"], ranges["upper"])
                color_prev = cv2.inRange(hsv_prev, ranges["lower"], ranges["upper"])
                new_color = cv2.bitwise_and(color_curr, cv2.bitwise_not(color_prev))
                new_bright = cv2.bitwise_or(new_bright, new_color)

            score = cv2.countNonZero(new_bright)
            sparkle_scores.append(score)

        if not sparkle_scores:
            return False

        # Sparkle animation = multiple consecutive frames with new bright pixels.
        # Normal battle transitions might have 1 spike; sparkles have 3+.
        active_frames = sum(1 for s in sparkle_scores if s >= 15)
        max_score = max(sparkle_scores)

        triggered = active_frames >= 3 and max_score >= 40
        logger.info(
            f"[sparkle anim] active_frames={active_frames}/{len(sparkle_scores)}, "
            f"max={max_score}, triggered={triggered}"
        )
        return triggered

    # ------------------------------------------------------------------
    # Universal palette / dominant-hue detection
    # ------------------------------------------------------------------

    def detect_by_dominant_hue(self, frame: np.ndarray, target: str) -> Optional[bool]:
        """
        Classify shiny/normal by extracting the dominant body hue from the sprite
        region and comparing against the FRLG palette database.

        Works for any Pokemon with a palette entry — no reference images needed.

        Returns:
          True  — dominant hue matches shiny range
          False — dominant hue matches normal range
          None  — no palette entry, or inconclusive (overlapping ranges)
        """
        entry = get_palette(target)
        if entry is None:
            return None

        # Crop sprite region
        sprite = self._get_sprite_region(frame)
        hsv = cv2.cvtColor(sprite, cv2.COLOR_BGR2HSV)

        # Keep only "body" pixels (enough saturation + value to be colored)
        sat_mask = hsv[:, :, 1] >= entry.min_sat
        val_mask = hsv[:, :, 2] >= entry.min_val
        body_mask = sat_mask & val_mask

        body_hues = hsv[:, :, 0][body_mask]
        if len(body_hues) < 20:
            logger.info(f"[palette] {target}: too few body pixels ({len(body_hues)}), skipping")
            return None

        # Build hue histogram and find the dominant peak
        hist = cv2.calcHist([body_hues.reshape(-1, 1).astype(np.float32)],
                            [0], None, [180], [0, 180]).flatten()

        # Smooth the histogram to avoid noise peaks
        kernel = np.ones(5) / 5
        hist_smooth = np.convolve(hist, kernel, mode='same')
        dominant_hue = int(np.argmax(hist_smooth))

        result = classify_hue(target, dominant_hue)
        label = {True: "SHINY", False: "normal", None: "inconclusive"}[result]
        logger.info(
            f"[palette] {target}: dominant_hue={dominant_hue}, "
            f"normal_range={entry.normal_hues}, shiny_range={entry.shiny_hues} "
            f"→ {label}"
        )

        # For subtle shinies, only trust "shiny" if sparkle also triggered
        if entry.subtle and result is True:
            logger.info(f"[palette] {target}: subtle shiny — needs sparkle confirmation")
            return None  # let sparkle detection be the deciding factor

        return result

    def check_window(self, frames: List[np.ndarray], target: Optional[str] = None, encounter: int = 0) -> ShinyDetectionResult:
        """
        Five-tier shiny detection — ANY positive tier = shiny.  All must agree
        NOT shiny to reset.  This ensures we never miss a shiny.

          Tier 1: Sparkle animation (frame differencing)  — universal, no setup
          Tier 2: Dominant hue / palette check             — universal for known species
          Tier 3: Reference image comparison               — when ref images exist
          Tier 4: HSV body-color range check               — when color profile exists
          Tier 5: Sparkle pixel counting (legacy fallback) — last resort
        """
        if not frames:
            return ShinyDetectionResult(is_shiny=False, confidence=0.0)

        # -- Tier 1: Universal sparkle animation (frame differencing) --
        sparkle_anim = self.detect_sparkle_animation(frames)

        # -- Tier 2: Dominant hue / palette classification --
        palette_result = None
        if target:
            palette_result = self.detect_by_dominant_hue(frames[-1], target)

        # -- Tier 3: Reference image comparison --
        ref_result = None
        if target:
            has_ref = self._get_cached_sprite_crop(target, shiny=True) is not None
            if has_ref:
                ref_result = self.confirm_shiny_by_reference(frames[-1], target)

        # -- Tier 4: HSV body-color range check --
        color_result = None
        if target:
            has_colors = bool(POKEMON_BODY_COLORS.get(target.lower()))
            if has_colors:
                color_result = self.confirm_shiny_by_color(frames[-1], target)

        # -- Tier 5: Sparkle pixel counting (legacy) --
        # Only trust this if there's actual variation between frames (rules out
        # static bright pixels in the HP bar / text box that would false-positive).
        counts = [self._count_sparkle_pixels(f) for f in frames]
        max_count = max(counts)
        min_count = min(counts)
        avg_count = sum(counts) / len(counts)
        has_variation = (max_count - min_count) > max(self.threshold * 0.3, 10)
        sparkle_pixels = (
            has_variation
            and max_count >= self.threshold
            and avg_count >= self.threshold * 0.4
        )

        # -- Decision logic --
        # Species-specific tiers (palette, reference, color) are high-confidence.
        # Sparkle-based tiers (sparkle_anim, sparkle_px) can false-positive from
        # scene transitions, camera noise, HP bar flashes, etc.  When we HAVE
        # species data, sparkle tiers alone are NOT enough — they need at least
        # one species tier to NOT contradict them (i.e. no species tier said
        # "normal").  When no species data exists, sparkle tiers are trusted.
        has_species_tiers = (palette_result is not None
                            or ref_result is not None
                            or color_result is not None)
        any_species_positive = (palette_result is True
                                or ref_result is True
                                or color_result is True)
        any_species_negative = (palette_result is False
                                or ref_result is False
                                or color_result is False)

        # Sparkle tiers: trusted alone only when no species data exists,
        # OR when at least one species tier agrees.
        # Blocked if ANY species tier explicitly says "normal".
        sparkle_anim_counts = sparkle_anim and (
            any_species_positive or not has_species_tiers
        ) and not (has_species_tiers and any_species_negative and not any_species_positive)

        sparkle_px_counts = sparkle_pixels and (
            any_species_positive or not has_species_tiers
        )

        is_shiny = (
            sparkle_anim_counts
            or palette_result is True
            or ref_result is True
            or color_result is True
            or sparkle_px_counts
        )

        # Build triggered-by list for logging
        triggered_by = []
        if sparkle_anim:
            if sparkle_anim_counts:
                triggered_by.append("sparkle_anim")
            else:
                triggered_by.append("sparkle_anim(ignored)")
        if palette_result is True:  triggered_by.append("palette")
        if ref_result is True:      triggered_by.append("reference")
        if color_result is True:    triggered_by.append("color")
        if sparkle_pixels:
            if sparkle_px_counts:
                triggered_by.append("sparkle_px")
            else:
                triggered_by.append("sparkle_px(ignored)")

        if is_shiny:
            logger.info(f"[detection] {target}: *** SHINY *** confirmed by: {', '.join(triggered_by)}")
        else:
            logger.info(
                f"[detection] {target}: not shiny ("
                f"sparkle_anim={'yes' if sparkle_anim else 'no'}, "
                f"palette={'yes' if palette_result else 'no' if palette_result is False else 'n/a'}, "
                f"ref={'yes' if ref_result else 'no' if ref_result is False else 'n/a'}, "
                f"color={'yes' if color_result else 'no' if color_result is False else 'n/a'}, "
                f"sparkle_px={'yes' if sparkle_pixels else 'no'})"
            )

        # Save screenshot for every encounter
        if target:
            enc_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", "..", "tools", "screenshots", "encounters")
            )
            os.makedirs(enc_dir, exist_ok=True)
            cv2.imwrite(os.path.join(enc_dir, f"{target}_{encounter:05d}_full.png"), frames[-1])
            sprite_crop = self._get_sprite_region(frames[-1])
            label = "SHINY" if is_shiny else "normal"
            cv2.imwrite(os.path.join(enc_dir, f"{target}_{encounter:05d}_crop_{label}.png"), sprite_crop)

        confidence = 1.0 if is_shiny else 0.0
        best_idx = counts.index(max_count)

        return ShinyDetectionResult(
            is_shiny=is_shiny,
            confidence=confidence,
            frame=frames[best_idx].copy() if frames else None,
            sparkle_triggered=sparkle_anim or sparkle_pixels,
            color_confirmed=color_result,
        )

    # ------------------------------------------------------------------
    # Stage 2: body color confirmation
    # ------------------------------------------------------------------

    def _get_sprite_region(self, frame: np.ndarray) -> np.ndarray:
        """Crop to the Pokemon sprite area only — excludes HP bar."""
        h, w = frame.shape[:2]
        top    = int(POKEMON_SPRITE_REGION["top"]    * h)
        left   = int(POKEMON_SPRITE_REGION["left"]   * w)
        bottom = int(POKEMON_SPRITE_REGION["bottom"] * h)
        right  = int(POKEMON_SPRITE_REGION["right"]  * w)
        return frame[top:bottom, left:right]

    def confirm_shiny_by_color(self, frame: np.ndarray, target: str) -> Optional[bool]:
        """
        Check the Pokemon sprite region for shiny vs normal colors.
        Uses POKEMON_SPRITE_REGION (excludes HP bar) to avoid false positives
        from the green HP bar when the Pokemon is at full health.
        """
        profile = POKEMON_BODY_COLORS.get(target.lower())
        if profile is None:
            return None

        # Use tight sprite region — NOT battle region — to exclude the HP bar
        region = self._get_sprite_region(frame)
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        threshold = profile["confirm_threshold"]

        shiny_mask  = cv2.inRange(hsv, profile["shiny"]["lower"],  profile["shiny"]["upper"])
        normal_mask = cv2.inRange(hsv, profile["normal"]["lower"], profile["normal"]["upper"])

        shiny_pixels  = cv2.countNonZero(shiny_mask)
        normal_pixels = cv2.countNonZero(normal_mask)

        logger.info(f"[color check] {target}: shiny_pixels={shiny_pixels}, normal_pixels={normal_pixels}, threshold={threshold}")

        # Save the cropped sprite region so we can verify what's being analyzed
        os.makedirs("tools/screenshots/color_checks", exist_ok=True)
        existing = len(os.listdir("tools/screenshots/color_checks"))
        cv2.imwrite(f"tools/screenshots/color_checks/{target}_{existing:04d}_full.png", frame)
        cv2.imwrite(f"tools/screenshots/color_checks/{target}_{existing:04d}_crop.png", region)

        return shiny_pixels >= threshold and shiny_pixels > normal_pixels



    def is_battle_screen(self, frame: np.ndarray) -> bool:
        """
        Rough check: is the current frame likely a battle screen?
        Uses the characteristic black/dark top bar of the FRLG battle UI.
        """
        if frame is None:
            return False
        h, w = frame.shape[:2]
        top_strip = frame[0:int(h * 0.08), :]
        gray = cv2.cvtColor(top_strip, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 20, 255, cv2.THRESH_BINARY_INV)
        black_ratio = cv2.countNonZero(thresh) / (top_strip.shape[0] * top_strip.shape[1])
        return black_ratio > 0.70

    def is_title_screen(self, frame: np.ndarray) -> bool:
        """
        Detect the FRLG title screen (appears after soft reset).
        Fire Red has a fiery orange background; Leaf Green has a green one.
        """
        if frame is None:
            return False
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        total = frame.shape[0] * frame.shape[1]

        fire_red  = cv2.inRange(hsv, np.array([5, 100, 150]), np.array([20, 255, 255]))
        leaf_green = cv2.inRange(hsv, np.array([40, 80, 100]), np.array([80, 255, 200]))

        return (cv2.countNonZero(fire_red) / total > 0.15 or
                cv2.countNonZero(leaf_green) / total > 0.15)
