# `src/rng/frlg_rng.py` — Documentation

## Purpose

Implements the Gen-3 (FireRed/LeafGreen) Pseudo-Random Number Generator (PRNG)
and shiny frame calculations. Used by the RNG tools to predict which game frames
will produce a shiny Pokémon for a given Trainer ID and Secret ID.

---

## Background: Gen-3 RNG

FRLG always boots with seed `0x00000000` (no real-time clock unlike Emerald).
The PRNG is a Linear Congruential Generator (LCG):

$$\text{seed}_{n+1} = (0x41C64E6D \times \text{seed}_n + 0x6073) \bmod 2^{32}$$

Each call to the PRNG advances the seed and returns the upper 16 bits as the
"random" output value.

---

## Shiny Check (Method 1 — Static Encounters)

Static legendaries (Mewtwo, birds, Ho-Oh, Lugia, Deoxys) use **Method 1**:

```
Frame N:   seed → PID_low  (lower 16 bits of PID)
Frame N+1: seed → PID_high (upper 16 bits of PID)
Frame N+2: seed → IV_set1
Frame N+3: seed → IV_set2
```

PID = `(PID_high << 16) | PID_low`

A Pokémon is **shiny** when:
$$\text{TID} \oplus \text{SID} \oplus \text{PID\_high} \oplus \text{PID\_low} < 8$$

---

## Functions

### `prng_advance(seed: int) -> int`
Advances the PRNG one step and returns the new seed.

```python
next_seed = prng_advance(0x00000000)  # → 0x00006073
```

---

### `prng_next16(seed: int) -> (int, int)`
Returns `(new_seed, upper_16_bits)`.
The upper 16 bits are the "random value" used to generate PID components.

```python
seed, value = prng_next16(seed)
```

---

### `seed_at_frame(frame: int, initial_seed: int = 0) -> int`
Advances the PRNG from `initial_seed` exactly `frame` times.
Used to fast-forward to a specific frame without iterating in the main loop.

```python
seed = seed_at_frame(1000)  # seed after 1000 PRNG advances from boot
```

---

### `is_shiny(tid: int, sid: int, pid: int) -> bool`
Returns `True` if `pid` is shiny for the given `tid`/`sid` pair.

```python
is_shiny(tid=59556, sid=43992, pid=0x3B8378FD)  # → True (your Mewtwo)
```

---

### `find_shiny_frames(tid, sid, frame_min=0, frame_max=100_000, nature_filter=None) -> list[dict]`
Enumerates all Method-1 frames that produce a shiny PID for the given trainer IDs.

**Parameters:**
- `tid` — Trainer ID (0–65535)
- `sid` — Secret ID (0–65535)
- `frame_min` — first frame to check (default 0)
- `frame_max` — last frame to check (default 100,000)
- `nature_filter` — optional nature name to filter results (e.g. `"Timid"`)

**Returns:** List of dicts:
```json
[
  {
    "frame": 1597,
    "pid": "0x3B8378FD",
    "nature": "Impish",
    "ivs": {"hp": 31, "atk": 20, "def": 25, "spa": 15, "spd": 18, "spe": 22},
    "is_shiny": true
  }
]
```

---

### `NATURES`
List of all 25 Pokémon natures in Gen-3 order (index = `pid % 25`):
```python
["Hardy", "Lonely", "Brave", "Adamant", "Naughty", ...]
```

---

## IV Calculation

IVs are unpacked from `IV_set1` and `IV_set2`:
```
IV_set1 (16 bits): HP[4:0], Atk[9:5], Def[14:10]
IV_set2 (16 bits): Speed[4:0], SpA[9:5], SpD[14:10]
```
Each stat gets 5 bits → range 0–31.

---

## RNG Tools (in `tools/`)

| Tool | Purpose |
|------|---------|
| `find_shiny_frame.py` | Find which frame will produce a shiny for your TID/SID |
| `find_sid.py` | Determine your SID from a known shiny PID |
| `calc_sid_now.py` | Calculate SID given video timestamp offset |
| `calc_sid_reverse.py` | Reverse SID from observed stats + nature |
| `sweep_seed.py` | Sweep all seeds for shiny frames |
| `replay_seed.py` | Replay a specific seed to verify PID generation |

---

## Your Profile

From `data/hunt_profile.json`:
- TID: **59556**
- SID: **43992**
- Confirmed shiny Mewtwo: frame **1597**, PID `0x3B8378FD`, Nature: **Impish**
