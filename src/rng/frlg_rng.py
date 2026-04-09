"""
FRLG RNG Engine
===============
Core Gen-3 PRNG routines for FireRed / LeafGreen.

FRLG always boots with seed 0x00000000 (no RTC).  The PRNG is a simple LCG:
    seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF

Method 1 (static encounters — Mewtwo, birds, Ho-Oh, Lugia, Deoxys):
    seed → PID_low → PID_high → IV_set1 → IV_set2

A Pokémon is shiny when:
    (TID ^ SID ^ PID_high ^ PID_low) < 8
"""


def prng_advance(seed: int) -> int:
    """Advance the Gen-3 PRNG one step."""
    return (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF


def prng_next16(seed: int) -> tuple[int, int]:
    """Return (new_seed, upper-16-bit value)."""
    seed = prng_advance(seed)
    return seed, seed >> 16


def seed_at_frame(frame: int, initial_seed: int = 0) -> int:
    """FRLG boots from seed 0. Advance `frame` times."""
    seed = initial_seed
    for _ in range(frame):
        seed = prng_advance(seed)
    return seed


def is_shiny(tid: int, sid: int, pid: int) -> bool:
    """Check if a PID is shiny for the given TID/SID."""
    return (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8


NATURES = [
    "Hardy",   "Lonely", "Brave",   "Adamant", "Naughty",
    "Bold",    "Docile", "Relaxed", "Impish",  "Lax",
    "Timid",   "Hasty",  "Serious", "Jolly",   "Naive",
    "Modest",  "Mild",   "Quiet",   "Bashful", "Rash",
    "Calm",    "Gentle", "Sassy",   "Careful", "Quirky",
]


def find_shiny_frames(
    tid: int,
    sid: int,
    frame_min: int = 0,
    frame_max: int = 100_000,
    nature_filter: str | None = None,
) -> list[dict]:
    """
    Enumerate all Method-1 frames that produce a shiny PID for the given TID/SID.

    Returns list of dicts with keys:
        frame, pid, nature, ivs (dict), is_shiny
    """
    seed = seed_at_frame(frame_min)
    results = []

    for frame in range(frame_min, frame_max + 1):
        s0 = seed

        s1, r1 = prng_next16(s0)   # PID low
        s2, r2 = prng_next16(s1)   # PID high
        s3, r3 = prng_next16(s2)   # IV set 1
        s4, r4 = prng_next16(s3)   # IV set 2

        pid = (r2 << 16) | r1
        xor = tid ^ sid ^ r2 ^ r1

        if xor < 8:
            nature_name = NATURES[pid % 25]
            if nature_filter and nature_name.lower() != nature_filter.lower():
                seed = prng_advance(seed)
                continue

            ivs = {
                "hp":  r3 & 0x1F,
                "atk": (r3 >> 5) & 0x1F,
                "def": (r3 >> 10) & 0x1F,
                "spa": r4 & 0x1F,
                "spd": (r4 >> 5) & 0x1F,
                "spe": (r4 >> 10) & 0x1F,
            }
            results.append({
                "frame":  frame,
                "pid":    f"{pid:08X}",
                "nature": nature_name,
                "ivs":    ivs,
            })

        seed = prng_advance(seed)

    return results


# ── Frame-to-timing conversion ───────────────────────────────────────────────
# FRLG GBA runs at ~59.7275 fps (16.7427 ms/frame).
# The PRNG advances once per frame during gameplay.
# The critical control point is the delay before pressing START on the title
# screen — this determines which seed the game latches onto.
#
# After loading a save (CONTINUE), there is a FIXED number of frames consumed
# by the loading sequence (menus, memories skip, overworld load, walking to
# target, battle intro).  We call this the "base frame offset".
#
# The relationship is:
#   target_frame = base_offset + extra_frames_from_jitter
#   jitter_ms ≈ extra_frames * 16.743
#
# The base offset must be calibrated per-target (it depends on the exact save
# position and button sequence).  A reasonable starting estimate for Mewtwo
# is ~1000-3000 frames consumed from CONTINUE to encounter generation.

GBA_FRAME_MS = 16.7427  # milliseconds per GBA frame at 59.7275 Hz


def frame_to_jitter_ms(target_frame: int, base_offset: int) -> float:
    """
    Convert a target PRNG frame number into the approximate START jitter (ms)
    needed to hit it.

    target_frame: the PRNG frame that produces the shiny PID
    base_offset:  frames consumed by the fixed loading sequence (CONTINUE → encounter)

    Returns: jitter in milliseconds to wait before pressing START.
             Negative values mean the frame is before the base offset (unreachable).
    """
    extra_frames = target_frame - base_offset
    return extra_frames * GBA_FRAME_MS


def jitter_ms_to_frame(jitter_ms: float, base_offset: int) -> int:
    """Inverse: given a jitter in ms, what PRNG frame would we hit?"""
    extra_frames = round(jitter_ms / GBA_FRAME_MS)
    return base_offset + extra_frames
