"""Quick hue analysis of shiny vs normal Mewtwo to calibrate palette ranges."""
import cv2
import numpy as np
import os

BASE = os.path.join(os.path.dirname(__file__), "..")

SR = {"top": 0.08, "left": 0.52, "bottom": 0.52, "right": 0.95}

for name, path in [
    ("SHINY", os.path.join(BASE, "data", "reference_shinies", "mewtwo_shiny.png")),
    ("NORMAL", os.path.join(BASE, "data", "reference_normals", "mewtwo_normal.png")),
]:
    img = cv2.imread(path)
    h, w = img.shape[:2]
    sprite = img[int(SR["top"] * h) : int(SR["bottom"] * h), int(SR["left"] * w) : int(SR["right"] * w)]
    hsv = cv2.cvtColor(sprite, cv2.COLOR_BGR2HSV)

    print(f"\n=== {name} ({path}) ===")
    print(f"  Sprite crop: {sprite.shape[1]}x{sprite.shape[0]}")

    for min_sat in [25, 50, 80, 120]:
        body = (hsv[:, :, 1] >= min_sat) & (hsv[:, :, 2] >= 80)
        hues = hsv[:, :, 0][body]
        if len(hues) < 10:
            print(f"  sat>={min_sat}: only {len(hues)} pixels")
            continue
        hist = np.bincount(hues.flatten(), minlength=180)
        top5 = np.argsort(hist)[-5:][::-1]
        print(f"  sat>={min_sat}: {len(hues)} px  top: " +
              ", ".join(f"H={v}({hist[v]})" for v in top5))

    # Also check specific hue ranges
    for label, h_lo, h_hi in [
        ("green(40-85)", 40, 85),
        ("purple(120-160)", 120, 160),
        ("tan/bg(15-35)", 15, 35),
        ("white(low-sat)", 0, 179),
    ]:
        if label == "white(low-sat)":
            mask = (hsv[:, :, 1] < 25) & (hsv[:, :, 2] >= 150)
        else:
            mask = (hsv[:, :, 0] >= h_lo) & (hsv[:, :, 0] <= h_hi) & (hsv[:, :, 1] >= 40) & (hsv[:, :, 2] >= 80)
        count = np.count_nonzero(mask)
        print(f"  {label}: {count} pixels")
