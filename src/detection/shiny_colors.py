import numpy as np
import json
from pathlib import Path

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

# Battle screen region — used for sparkle pixel counting.
# Wide enough to catch sparkle stars around the Pokemon.
BATTLE_REGION = {
    "top":    0.05,
    "left":   0.35,
    "bottom": 0.55,
    "right":  0.95,
}

# Pokemon sprite region — used for body COLOR checks only.
# Deliberately excludes the HP bar (top-left) which is green when HP is full
# and would cause false positives. Targets the actual sprite area.
POKEMON_SPRITE_REGION = {
    "top":    0.08,   # skip the HP bar row
    "left":   0.52,   # far enough right to clear the HP bar entirely
    "bottom": 0.52,
    "right":  0.95,
}

# ---------------------------------------------------------------------------
# Per-Pokemon body color profiles for secondary "color confirmation" check.
#
# After the sparkle window, we sample the Pokemon's body region and check
# which color profile best matches — this double-confirms a shiny.
#
# How to calibrate:
#   Run tools/sample_colors.py with a screenshot of the Pokemon in battle.
#   It will print the average HSV of the sampled region.
#
# OpenCV HSV: H 0-180, S 0-255, V 0-255
# ---------------------------------------------------------------------------
#
# Each entry can optionally include:
#   "reference_match_threshold": float (0.0-1.0, default 0.70)
#     Only used when a shiny reference image exists but NO normal reference image.
#     The live sprite's histogram must match the shiny reference at least this well.
#     Lower = more lenient (catches subtle shinies but may false-positive).
#     Higher = stricter (misses subtle shinies but more reliable).
#     When BOTH shiny and normal reference images exist, this threshold is ignored
#     and the closer match wins instead.
#
# ---------------------------------------------------------------------------
POKEMON_BODY_COLORS = {}

# --- Load auto-generated body-color profiles for all 386 Pokémon ---
_GENERATED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sprites" / "frlg" / "body_colors_generated.py"
if _GENERATED_PATH.exists():
    _ns = {}
    exec(compile(_GENERATED_PATH.read_text(encoding="utf-8"), str(_GENERATED_PATH), "exec"), _ns)
    for _name, _profile in _ns.get("POKEMON_BODY_COLORS", {}).items():
        POKEMON_BODY_COLORS[_name] = {
            "normal": {
                "lower": np.array(_profile["normal"]["lower"]),
                "upper": np.array(_profile["normal"]["upper"]),
            },
            "shiny": {
                "lower": np.array(_profile["shiny"]["lower"]),
                "upper": np.array(_profile["shiny"]["upper"]),
            },
            "confirm_threshold": _profile.get("confirm_threshold", 50),
        }

# --- Hand-calibrated overrides (from actual game captures) ---
# These take priority over auto-generated data.
POKEMON_BODY_COLORS["mewtwo"] = {
    "normal": {
        "lower": np.array([120, 40,  80]),
        "upper": np.array([160, 255, 255]),
    },
    "shiny": {
        "lower": np.array([35,  40,  80]),
        "upper": np.array([85,  255, 255]),
    },
    "confirm_threshold": 200,
    "reference_match_threshold": 0.74,
}
# Zapdos: shiny is a slightly darker/oranger yellow (median hue ~22) vs
# normal bright yellow (median hue ~27).  Boundary at H=24 avoids overlap.
POKEMON_BODY_COLORS["zapdos"] = {
    "normal": {
        "lower": np.array([24, 150, 180]),
        "upper": np.array([35, 255, 255]),
    },
    "shiny": {
        "lower": np.array([4,  150, 100]),
        "upper": np.array([23, 255, 255]),
    },
    "confirm_threshold": 40,
}
POKEMON_BODY_COLORS["moltres"] = {
    "normal": {
        "lower": np.array([5,  180, 180]),
        "upper": np.array([18, 255, 255]),
    },
    "shiny": {
        "lower": np.array([22, 180, 180]),
        "upper": np.array([35, 255, 255]),
    },
    "confirm_threshold": 40,
}
# Articuno: normal and shiny share the same hue (~106 blue), but differ in
# SATURATION.  Normal has many high-sat (S>=140) blue pixels; shiny is much
# lighter / less saturated (S 20-80).  We exploit this saturation gap.
POKEMON_BODY_COLORS["articuno"] = {
    "normal": {
        "lower": np.array([95,  140, 80]),
        "upper": np.array([125, 255, 255]),
    },
    "shiny": {
        "lower": np.array([100, 20,  140]),
        "upper": np.array([115, 80,  255]),
    },
    "confirm_threshold": 30,
}
# Ho-Oh: normal = red/orange/gold, shiny = yellow/gold (more saturated yellow)
POKEMON_BODY_COLORS["ho-oh"] = {
    "normal": {
        "lower": np.array([0,   150, 150]),
        "upper": np.array([15,  255, 255]),
    },
    "shiny": {
        "lower": np.array([15,  150, 150]),
        "upper": np.array([35,  255, 255]),
    },
    "confirm_threshold": 50,
}
# Lugia: both forms are mostly white; normal has some saturated blue
# (H=95-120, S>=120), shiny adds unique pink/red pixels (H=155-180)
# that normal entirely lacks.  Narrow normal S range prevents shiny's
# blue from dominating the count.
POKEMON_BODY_COLORS["lugia"] = {
    "normal": {
        "lower": np.array([95,  120, 100]),
        "upper": np.array([125, 255, 255]),
    },
    "shiny": {
        "lower": np.array([155, 30,  100]),
        "upper": np.array([180, 255, 255]),
    },
    "confirm_threshold": 20,
}
# Deoxys: normal = orange/red, shiny = yellow/green tinted
POKEMON_BODY_COLORS["deoxys"] = {
    "normal": {
        "lower": np.array([5,   150, 150]),
        "upper": np.array([18,  255, 255]),
    },
    "shiny": {
        "lower": np.array([20,  150, 150]),
        "upper": np.array([45,  255, 255]),
    },
    "confirm_threshold": 40,
}
