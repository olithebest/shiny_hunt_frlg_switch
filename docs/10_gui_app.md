# `src/gui/app.py` — Documentation

## Purpose

Streamlit-based graphical interface for the Shiny Hunter system.
Provides a browser-based dashboard for configuring, starting, monitoring,
and stopping automated shiny hunts. Runs locally on the user's machine.

**Launch command:**
```bash
streamlit run src/gui/app.py
```

---

## Architecture

The GUI uses Streamlit's session state to bridge two execution contexts:
- **Main thread** — Streamlit UI render loop (re-runs every interaction or timer tick)
- **Hunt thread** — background `daemon` thread owning `CaptureHandler`, `SwitchController`, and `HuntSequence`

```
Browser ──▶ Streamlit main thread ──▶ Hunt daemon thread
                  │                        │
                  │  session_state         │  add_log(), _on_encounter()
                  └────────────────────────┘
```

The UI polls for updates every 2 seconds while a hunt is active (`time.sleep(2)` + `st.rerun()`).

---

## Session State Variables

| Key | Type | Description |
|-----|------|-------------|
| `running` | `bool` | True while hunt thread is active |
| `encounters` | `int` | Total encounter count this session |
| `shiny_found` | `bool` | True once a shiny is detected |
| `log_messages` | `list[str]` | Timestamped log lines (max 200) |
| `start_time` | `datetime` | When the current hunt started |
| `hunt_thread` | `Thread` | Reference to daemon thread |
| `sequence` | `HuntSequence` | Live sequence object (used to call `.stop()`) |
| `last_frame` | `ndarray` | Last captured frame — shown on shiny detection |

---

## Functions

### `load_settings() -> dict`
Reads `config/settings.yaml` and returns it as a dict.
Used to pre-populate sidebar fields with saved defaults.

---

### `add_log(msg: str)`
Appends a timestamped log entry to `session_state.log_messages`.
Trims to the last 200 messages to avoid unbounded growth.
Called from the hunt thread via the `on_status` callback.

---

### `run_hunt_thread(capture_idx, target, ctrl_mode, serial_port)`
Runs in a background daemon thread. Owns the full hardware lifecycle:

1. Instantiates `CaptureHandler`, `ShinyDetector`, `SwitchController`
2. Creates `HuntSequence` with `on_status` → `add_log` and `on_encounter` → `_on_encounter`
3. Opens the capture device and connects the controller
4. Calls `sequence.run()` — blocks until shiny found or `stop()` called
5. On shiny: logs result, sets `shiny_found = True`, stores the frame
6. On exception: logs error, propagates via `add_log`
7. Always closes capture + disconnects controller in `finally`
8. Sets `session_state.running = False` when done

---

### `_on_encounter(count: int, is_shiny: bool)`
Callback from `HuntSequence`. Updates `session_state.encounters` and sets
`shiny_found = True` if triggered on a shiny frame.

---

## UI Layout

### Sidebar (Configuration)
| Control | Purpose |
|---------|---------|
| Capture Card Device Index | Which OpenCV device to open (0 = first camera) |
| Target Pokémon | Dropdown — only unlocked hunts appear; locked if no license |
| Controller Mode | Keyboard (emulator only) or Serial (real Switch via Arduino) |
| Arduino Serial Port | Visible only when Serial mode selected; e.g. `COM3` |

If no hunts are unlocked, a warning is shown with instructions to run `store_server.py`.

---

### Main Area

#### Preview Column (2/3 width)
- **Grab Preview Frame** button — opens the capture device for one frame, displays it
- On shiny detection — replaces preview with the captured shiny frame

#### Stats Column (1/3 width)
| Metric | Description |
|--------|------------|
| Status banner | Idle / Hunt in progress / SHINY FOUND |
| Total Encounters | Live counter |
| Elapsed Time | HH:MM:SS since hunt started |
| Resets / min | Calculated as `encounters / elapsed_minutes` |

---

### Control Buttons

| Button | Behavior |
|--------|---------|
| ▶ Start Hunting | Resets counters, starts daemon thread, calls `st.rerun()` |
| ⏹ Stop | Calls `sequence.stop()`, sets `running = False`, reruns |
| 🔄 Reset Stats | Clears counters + log without stopping the hunt |

Start is disabled when: hunt is running, shiny already found, or no target selected (no license).

---

### Activity Log
- Shows last 40 messages from `log_messages` in reverse order (newest on top)
- Updates automatically every 2 seconds while running
- Shown as a read-only text area

---

## Auto-Refresh Loop

```python
if st.session_state.running:
    time.sleep(2)
    st.rerun()
```

While a hunt is active, the page automatically re-renders every 2 seconds to
pick up updated encounter counts and log messages from the hunt thread.

---

## License Integration

At startup:
```python
unlocked_hunts = get_unlocked_hunts()
```

If `unlocked_hunts` is empty, the target dropdown is hidden and a warning is shown.
If populated, the target dropdown is built from `HUNT_CATALOGUE` display names.

This ensures the GUI enforces the license requirement without any separate check.

---

## Running Without a License (Development)

Activate a key via `tools/store_server.py` first, then launch the GUI:
```bash
python tools/store_server.py      # localhost:5050 — activate key
streamlit run src/gui/app.py      # open browser
```

---

## Dependencies

| Package | Use |
|---------|-----|
| `streamlit` | UI framework |
| `opencv-python` (`cv2`) | Frame capture and BGR→RGB conversion |
| `pyyaml` | Loading `config/settings.yaml` |
| `numpy` | Frame array type |
| `threading` | Background hunt thread |
