# Shiny Hunter FRLG — Code Documentation

This folder contains full professional documentation for every major file in
the project. Read this index first to understand the big picture, then dive
into individual files.

---

## System Overview

```
itch.io buyer purchases → cron-job.org hits /poll every 5 min
                        → Render (webhook_server.py) calls itch.io API
                        → generates HMAC-signed license key
                        → emails key via Mailjet to buyer

Buyer's machine:
  store_server.py (localhost:5050)
    → POST /api/activate with key
    → if local secret: validates HMAC locally
    → else: calls Render /validate-key
    → saves unlocked hunts to data/unlocked.json

  start.bat → Streamlit GUI (src/gui/app.py)
    → CaptureHandler reads Switch screen via OBS Virtual Camera
    → SwitchController sends button presses to Arduino over serial
    → Arduino impersonates a Switch Pro Controller via USB HID
    → ShinyDetector compares each encounter frame against reference image
    → If shiny detected → STOP and alert user
```

---

## Documentation Files

| File | What it covers |
|------|----------------|
| [01_license_manager.md](01_license_manager.md) | Key generation, HMAC signing, local activation |
| [02_webhook_server.md](02_webhook_server.md) | Purchase detection, email delivery, all HTTP endpoints |
| [03_store_server.md](03_store_server.md) | Buyer-side activation UI server |
| [04_switch_controller.md](04_switch_controller.md) | Button control (serial to Arduino) |
| [05_capture_handler.md](05_capture_handler.md) | Screen capture from OBS Virtual Camera |
| [06_shiny_detector.md](06_shiny_detector.md) | Three-tier shiny detection algorithm |
| [07_state_machine.md](07_state_machine.md) | Automation state tracking |
| [08_sequences.md](08_sequences.md) | Full hunt loop (soft-reset → encounter → detect) |
| [09_frlg_rng.md](09_frlg_rng.md) | Gen-3 PRNG — shiny frame math |
| [10_gui_app.md](10_gui_app.md) | Streamlit GUI overview |

---

## Key Files Map

```
tools/
  webhook_server.py     ← Render.com server — purchase → key → email
  store_server.py       ← Buyer's local activation UI (localhost:5050)

src/
  licensing/
    license_manager.py  ← HMAC key signing and validation
  automation/
    sequences.py        ← Full hunt loop logic
    state_machine.py    ← State enum + transition tracker
  capture/
    capture_handler.py  ← OpenCV video capture from capture card
  controller/
    switch_controller.py← Serial commands to Arduino
  detection/
    shiny_detector.py   ← Image comparison shiny detection
    shiny_colors.py     ← HSV fallback color ranges
    frlg_palettes.py    ← FRLG-specific palette classifications
  rng/
    frlg_rng.py         ← Gen-3 LCG PRNG math
  gui/
    app.py              ← Streamlit UI
    store.html          ← Activation page HTML

config/
  settings.yaml         ← All user-tunable timing and hardware settings

data/
  licenses.json         ← Keys activated by developer (local secret)
  unlocked.json         ← Hunts unlocked via Render validation (buyers)
  processed_purchases.json ← itch.io purchase IDs already emailed
  hunt_profile.json     ← TID / SID for shiny checking
  hunt_progress.json    ← Persistent encounter counter
```
