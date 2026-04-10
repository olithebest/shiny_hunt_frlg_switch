# `src/automation/sequences.py` — Documentation

## Purpose

Implements the full hunt loop: soft-reset → navigate to target → wait for battle
→ detect shiny → repeat. Coordinates `SwitchController`, `CaptureHandler`,
`ShinyDetector`, and `StateMachine` into a single runnable sequence.

---

## Data Classes

### `HuntResult`
Returned when a hunt loop iteration completes.

| Field | Type | Meaning |
|-------|------|---------|
| `is_shiny` | `bool` | Whether a shiny was found |
| `encounters` | `int` | Total encounter count so far |
| `frame` | `np.ndarray \| None` | The frame where shiny was detected |
| `detection_result` | `ShinyDetectionResult \| None` | Full detection output |

---

### `HuntConfig`
All timing parameters for a hunt, in seconds.

| Field | Default | When it fires |
|-------|---------|---------------|
| `intro_wait` | 3.5 s | After soft reset — wait for copyright screen to pass |
| `title_appear_wait` | 1.5 s | After skipping intro — wait for title screen |
| `menu_wait` | 1.0 s | After pressing A on title — wait for Continue menu |
| `memories_b_presses` | 6 | Number of B presses to skip "Previously on your quest" |
| `memories_b_interval` | 0.4 s | Delay between each B press |
| `world_load_wait` | 2.0 s | After memories dismissed — wait for overworld to load |
| `navigate_to_target_wait` | 1.0 s | After pressing A on target — wait |
| `cry_wait` | 0.0 s | For legendaries: wait for cry before A to enter battle |
| `battle_start_wait` | 3.5 s | After battle triggered — wait for intro animation |
| `sparkle_window_start` | 0.5 s | Offset into battle before sparkle check starts |
| `sparkle_window_duration` | 2.0 s | How long the sparkle window stays open |

---

## Function: `run_mewtwo_hunt(...)`

The main hunt loop for Mewtwo. Called once per soft-reset cycle.

```python
def run_mewtwo_hunt(
    controller: SwitchController,
    capture: CaptureHandler,
    detector: ShinyDetector,
    state_machine: StateMachine,
    config: HuntConfig,
    encounter_count: int,
    stop_event: threading.Event,
    on_frame: Callable[[np.ndarray], None] | None = None,
) -> HuntResult
```

### Parameters

| Parameter | Type | Purpose |
|-----------|------|---------|
| `controller` | `SwitchController` | Sends button presses to Switch |
| `capture` | `CaptureHandler` | Reads screen frames |
| `detector` | `ShinyDetector` | Determines if encounter is shiny |
| `state_machine` | `StateMachine` | Tracks current loop phase |
| `config` | `HuntConfig` | All timing values |
| `encounter_count` | `int` | Running total — passed in, returned incremented |
| `stop_event` | `threading.Event` | Set by GUI to stop the loop mid-run |
| `on_frame` | `callable \| None` | Optional callback — called with each grabbed frame for live preview |

### Return Value
`HuntResult` — contains `is_shiny`, updated `encounters`, and detection details.

---

## Mewtwo Hunt Step-by-Step

```
1. SOFT_RESETTING
   controller.soft_reset()        ← ZL+ZR+PLUS+MINUS

2. WAITING_FOR_RESET
   wait intro_wait seconds         ← copyright screen

3. WAITING_FOR_TITLE
   controller.press(A)             ← skip intro animation
   wait title_appear_wait          ← "PRESS START" screen

4. NAVIGATING_TO_TARGET
   controller.press(A)             ← title screen → main menu
   wait menu_wait
   controller.press(A)             ← select CONTINUE
   press B × memories_b_presses    ← dismiss memories screen
   wait world_load_wait            ← overworld loads
   controller.press(A)             ← interact with Mewtwo
   wait navigate_to_target_wait

5. WAITING_FOR_BATTLE
   if cry_wait > 0:
     wait cry_wait
     controller.press(A)           ← confirm to enter battle
   wait battle_start_wait          ← battle intro animation

6. CHECKING_FOR_SHINY
   frame = capture.grab_frame()
   result = detector.check(frame, "mewtwo")

   if result.is_shiny:
     state → SHINY_FOUND
     return HuntResult(is_shiny=True, ...)

   encounter_count += 1

7. (loop back to step 1)
```

---

## Thread Interaction

The GUI runs this function in a background `threading.Thread`.
`stop_event` is a `threading.Event` that the GUI sets when the user clicks Stop.
The loop checks `stop_event.is_set()` before each major step and returns early
with `is_shiny=False` if set.

`on_frame` is called from the background thread. If used to update a Streamlit
widget, updates must be dispatched safely (Streamlit's session state is thread-local).

---

## Adding a New Hunt Sequence

1. Copy `run_mewtwo_hunt()` as a starting template
2. Adjust the navigation steps (which buttons, how long to wait)
3. Change the target string passed to `detector.check(frame, "new_target")`
4. Register the new function in `gui/app.py`'s hunt selector
