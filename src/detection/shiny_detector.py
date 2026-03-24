import cv2
import numpy as np
from typing import Optional, List

from .shiny_colors import SPARKLE_STAR_COLORS, SPARKLE_PIXEL_THRESHOLD, BATTLE_REGION


class ShinyDetectionResult:
    def __init__(self, is_shiny: bool, confidence: float, frame: Optional[np.ndarray] = None):
        self.is_shiny = is_shiny
        self.confidence = confidence
        self.frame = frame

    def __repr__(self):
        return f"ShinyDetectionResult(is_shiny={self.is_shiny}, confidence={self.confidence:.2f})"


class ShinyDetector:
    """
    Detects shiny Pokemon in FRLG by analyzing the sparkle animation that
    plays at the start of battle when the Pokemon is shiny.

    The sparkle animation consists of bright multi-colored stars that
    spin around the Pokemon for ~1-2 seconds after it appears.

    Threshold tuning:
      - If you get false positives (non-shiny flagged as shiny)  → increase threshold
      - If you miss shinies (shiny not detected)                  → decrease threshold

    Usage:
        detector = ShinyDetector()
        result = detector.check_window(list_of_frames)
        if result.is_shiny:
            print("Shiny found!")
    """

    def __init__(self, threshold: int = SPARKLE_PIXEL_THRESHOLD):
        self.threshold = threshold

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
        """Check a single frame for shiny sparkle pixels."""
        count = self._count_sparkle_pixels(frame)
        confidence = min(count / max(self.threshold * 3, 1), 1.0)
        return ShinyDetectionResult(
            is_shiny=count >= self.threshold,
            confidence=confidence,
            frame=frame.copy(),
        )

    def check_window(self, frames: List[np.ndarray]) -> ShinyDetectionResult:
        """
        Check a sequence of frames captured during the sparkle window.
        More reliable than a single-frame check because the sparkle animation
        is sustained across multiple frames.
        """
        if not frames:
            return ShinyDetectionResult(is_shiny=False, confidence=0.0)

        counts = [self._count_sparkle_pixels(f) for f in frames]
        max_count = max(counts)
        avg_count = sum(counts) / len(counts)

        # Require both a strong peak and a sustained average
        is_shiny = (max_count >= self.threshold) and (avg_count >= self.threshold * 0.4)
        confidence = min(avg_count / max(self.threshold, 1), 1.0)

        best_idx = counts.index(max_count)
        return ShinyDetectionResult(
            is_shiny=is_shiny,
            confidence=confidence,
            frame=frames[best_idx].copy(),
        )

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
