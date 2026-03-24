import numpy as np

# ---------------------------------------------------------------------------
# HSV color ranges for Gen 3 (FRLG) shiny sparkle animation detection.
# OpenCV HSV: H 0-180, S 0-255, V 0-255
# ---------------------------------------------------------------------------

# The shiny sparkle animation consists of small multi-colored stars that
# spin around the Pokemon when it first appears in battle.
# We detect the presence of these bright saturated pixels.
SPARKLE_STAR_COLORS = {
    "white_bright": {
        "lower": np.array([0,   0,   220]),
        "upper": np.array([180, 30,  255]),
    },
    "yellow_gold": {
        "lower": np.array([20,  150, 200]),
        "upper": np.array([35,  255, 255]),
    },
    "blue_sparkle": {
        "lower": np.array([100, 150, 200]),
        "upper": np.array([130, 255, 255]),
    },
    "pink_sparkle": {
        "lower": np.array([145, 100, 200]),
        "upper": np.array([170, 255, 255]),
    },
}

# Minimum number of sparkle-matching pixels to classify a frame as shiny.
# Increase if getting false positives; decrease if missing shinies.
SPARKLE_PIXEL_THRESHOLD = 50

# Battle screen region as a fraction of the total frame dimensions.
# This is the area where the opposing Pokemon appears (upper-right quadrant).
BATTLE_REGION = {
    "top":    0.05,
    "left":   0.35,
    "bottom": 0.55,
    "right":  0.95,
}
