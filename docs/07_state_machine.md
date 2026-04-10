# `src/automation/state_machine.py` — Documentation

## Purpose

Tracks which phase of the hunt loop the automation is currently in.
Prevents invalid transitions (e.g. trying to detect shiny before entering battle)
and gives the GUI a clear status to display.

---

## `AutomationState` Enum

Each value represents a distinct phase of the automation:

| State | Meaning |
|-------|---------|
| `IDLE` | Not running — waiting for user to start |
| `WAITING_FOR_TITLE` | Soft reset done; waiting for the title screen to appear |
| `NAVIGATING_TO_TARGET` | On title/overworld; pressing buttons to reach the target |
| `WAITING_FOR_BATTLE` | A press confirmed; waiting for battle to start |
| `CHECKING_FOR_SHINY` | Battle started; running shiny detection on the frame |
| `SHINY_FOUND` | Shiny confirmed — automation stopped, alert shown |
| `SOFT_RESETTING` | Not shiny; triggering GBA soft reset combo |
| `WAITING_FOR_RESET` | Soft reset triggered; waiting for title screen |
| `STOPPED` | User manually stopped the hunt |
| `ERROR` | An unrecoverable error occurred |

---

## Class: `StateMachine`

### Constructor
```python
StateMachine(initial: AutomationState = AutomationState.IDLE)
```
Initializes with the given state (default: `IDLE`).

---

### `transition(new_state: AutomationState)`
Moves to a new state. No validation — any transition is allowed.
Log the state change externally if you need an audit trail.

```python
sm = StateMachine()
sm.transition(AutomationState.WAITING_FOR_BATTLE)
print(sm.state)  # AutomationState.WAITING_FOR_BATTLE
```

---

### `is_in(state: AutomationState) -> bool`
Returns `True` if the machine is currently in `state`.

```python
if sm.is_in(AutomationState.SHINY_FOUND):
    play_alert_sound()
```

---

### `__repr__`
```python
repr(sm)  # "StateMachine(state=CHECKING_FOR_SHINY)"
```

---

## Typical State Flow

```
IDLE
  ↓ user clicks Start
WAITING_FOR_TITLE
  ↓ title screen detected (or timeout)
NAVIGATING_TO_TARGET
  ↓ A pressed on target
WAITING_FOR_BATTLE
  ↓ battle start detected
CHECKING_FOR_SHINY
  ├── shiny detected → SHINY_FOUND (stop)
  └── not shiny     → SOFT_RESETTING
                          ↓
                     WAITING_FOR_RESET
                          ↓ (title appears)
                     WAITING_FOR_TITLE  (loop)
```
