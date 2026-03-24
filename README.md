# ✨ Shiny Hunter — Pokémon Fire Red / Leaf Green (Nintendo Switch)

Automate shiny hunting in **Pokémon Fire Red & Leaf Green** on the **Nintendo Switch Online GBA** app. The bot watches your capture card feed, detects the shiny sparkle animation with computer vision (OpenCV), and automatically soft-resets until a shiny appears.

---

## 📋 Table of Contents
1. [How it works](#how-it-works)
2. [Hardware requirements](#hardware-requirements)
3. [Software requirements](#software-requirements)
4. [Installation](#installation)
5. [Supported targets](#supported-targets)
6. [Usage](#usage)
7. [Controller setup (Arduino)](#controller-setup-arduino)
8. [Docker (optional)](#docker-optional)
9. [Troubleshooting](#troubleshooting)
10. [Project structure](#project-structure)

---

## How it works

```
Nintendo Switch
  │  (HDMI out)
  ▼
Capture Card (EZCap / any USB capture card)
  │  (USB video device)
  ▼
PC — OpenCV reads frames → detects shiny sparkle animation
  │
  ▼
Arduino Leonardo/Pro Micro (optional, recommended)
  │  (USB, acts as Switch Pro Controller)
  ▼
Nintendo Switch  ← receives button presses (A, soft-reset combo, etc.)
```

**Detection method:** When a shiny Pokémon appears in battle, Gen 3 plays a ~1.5 s sparkle animation with bright multi-colored stars. The detector captures several frames during that window and counts sparkle-colored pixels. If the count exceeds the threshold → shiny confirmed → bot stops and alerts you.

---

## Hardware requirements

| Item | Purpose | Notes |
|------|---------|-------|
| Nintendo Switch | Runs Pokémon FRLG via NSO GBA | Any model |
| HDMI capture card | Feeds Switch video to PC | EZCap, Elgato, generic USB capture cards all work |
| **Arduino Leonardo** or **Pro Micro** | Sends controller inputs to Switch | ~$5–15 on Amazon. **Optional** for testing; **required** for real automation |
| USB-A cable | Arduino → Switch USB port | Standard |
| PC (Windows / Linux / Mac) | Runs this software | Python 3.10+ required |

---

## Software requirements

- **Python 3.10 or newer** — [python.org/downloads](https://www.python.org/downloads/)  
  ✅ Check "Add Python to PATH" during installation

---

## Installation

### 1 — Clone this repository
```bash
git clone https://github.com/YOUR_USERNAME/shiny_hunt_frlg_switch.git
cd shiny_hunt_frlg_switch
```

### 2 — Run the setup script

**Windows:**
```
Double-click setup.bat
```

**Linux / Mac:**
```bash
pip install -r requirements.txt
```

### 3 — Launch the app

**Windows:**
```
Double-click start.bat
```

**Linux / Mac:**
```bash
streamlit run src/gui/app.py
```

The app opens at **http://localhost:8501** in your browser.

---

## Supported targets

| Pokémon | Location | Save position |
|---------|---------|--------------|
| Bulbasaur | Prof. Oak's Lab | Stand in front of the left Poké Ball |
| Charmander | Prof. Oak's Lab | Stand in front of the middle Poké Ball |
| Squirtle | Prof. Oak's Lab | Stand in front of the right Poké Ball |
| Lapras | Silph Co. 7F | Face the employee who gives Lapras |
| Eevee | Celadon Mansion rooftop | Face the aide |
| Zapdos | Power Plant | One step before Zapdos |
| Moltres | Victory Road | One step before Moltres |
| Articuno | Seafoam Islands | One step before Articuno |

> **Important:** Save your game at the correct position *before* starting the bot. It will load that save and repeat from there every cycle.

---

## Usage

1. Connect your capture card; open the NSO GBA app on your Switch.
2. Save at the correct position for your target Pokémon.
3. Open the app (`start.bat` or `streamlit run src/gui/app.py`).
4. In the sidebar, set:
   - **Capture Card Device Index** — usually `1` if you have a webcam, `0` if not
   - **Target Pokémon**
   - **Controller Mode** — `Serial (Arduino)` for real automation, `Keyboard` for testing
   - **Serial Port** — COM3 / COM4 (Windows) or `/dev/ttyUSB0` (Linux)
5. Click **🔍 Grab Preview Frame** to confirm the capture card is showing the game.
6. Click **▶ Start Hunting**.
7. The bot will run cycles automatically. When a shiny is found, it stops and shows the frame.

### Tuning detection sensitivity
Edit `config/settings.yaml`:
```yaml
detection:
  sparkle_threshold: 50        # lower = more sensitive, higher = fewer false positives
  sparkle_window_duration: 2.0 # how long to watch for sparkle (seconds)
```

---

## Controller setup (Arduino)

> Skip this section if you are testing with **Keyboard mode** on a PC emulator.

### Step 1 — Buy an Arduino Leonardo or Pro Micro
These use the ATmega32U4 chip, which supports USB HID natively.  
Search "Arduino Leonardo" or "Arduino Pro Micro" on Amazon (~$5–15).

### Step 2 — Install a Nintendo Switch HID library
In Arduino IDE → Sketch → Include Library → Manage Libraries → search for:
- **NSGamepad** (recommended), or
- **NintendoSwitchLibrary**

### Step 3 — Flash the sketch
Open `arduino/switch_controller/switch_controller.ino` in Arduino IDE.  
Follow the comments in the file to wire up the HID library calls.  
Upload to your Leonardo/Pro Micro.

### Step 4 — Connect Arduino to Switch
Plug the Arduino into the Nintendo Switch dock (or the Switch USB-C port with an adapter).  
The Switch will recognize it as a wired Pro Controller.

### Step 5 — Connect Arduino to PC
Plug the Arduino into your PC as well (it has two USB ports).  
In the app, select `Serial (Arduino)` and set the correct COM port.

---

## Docker (optional)

Docker is most useful on **Linux** where USB passthrough works natively.  
On **Windows and Mac**, run natively with `setup.bat` / `start.bat` instead.

### Fix Docker on Windows — Virtualization error
If Docker Desktop shows *"Virtualization support not detected"*:

1. **Restart your PC** and enter BIOS setup.  
   Press `Del` (MSI/ASUS/Gigabyte) or `F2` (ASRock/Dell) repeatedly at boot.
2. Navigate to **Advanced → CPU Configuration**.
3. Enable **Intel Virtualization Technology (VT-x)** → **Enabled**.
4. Enable **Intel VT-d** if present → **Enabled**.
5. **Save & Exit** (`F10`). Boot Windows and reopen Docker Desktop.

### Run with Docker (Linux)
```bash
docker compose up --build
```
App opens at **http://localhost:8501**.  
Edit `docker-compose.yml` to uncomment the `devices:` section and map your capture card and Arduino serial port.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Could not open capture device 0" | Try device index 1, 2, 3 in the sidebar |
| Capture preview is black / wrong window | Make sure the capture card software is closed — OpenCV reads the device directly |
| Bot never detects shiny | Lower `sparkle_threshold` in settings.yaml |
| Bot gives false positives | Raise `sparkle_threshold` |
| Serial port not found | Check Device Manager (Windows) for the Arduino COM port |
| Soft reset not working | Verify Arduino is connected to Switch; check serial port setting |
| Streamlit app won't start | Run `setup.bat` again to reinstall dependencies |

---

## Project structure

```
shiny_hunt_frlg_switch/
├── src/
│   ├── capture/          # Capture card interface (OpenCV VideoCapture)
│   ├── detection/        # Shiny sparkle detection (OpenCV HSV analysis)
│   ├── controller/       # Switch controller (keyboard test / Arduino serial)
│   ├── automation/       # Hunt sequences & state machine
│   └── gui/              # Streamlit web interface
├── config/
│   └── settings.yaml     # All tunable parameters
├── arduino/
│   └── switch_controller/
│       └── switch_controller.ino   # Arduino sketch
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── setup.bat             # Windows one-click install
└── start.bat             # Windows one-click launcher
```

---

## License
MIT — free to use, modify, and distribute.
