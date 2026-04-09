"""
Find Shiny Frames
=================
Given your TID + SID, searches for all PRNG frames that produce a shiny PID
for a target Pokémon in FRLG (Method 1 — static encounters).

Shows the best frames (sorted by IVs / nature), and calculates the approximate
START jitter timing your Arduino needs to hit each frame.

Usage:
  C:\\Python310\\python.exe tools/find_shiny_frame.py --tid 12345 --sid 54321 --target ho-oh
  C:\\Python310\\python.exe tools/find_shiny_frame.py --profile   --target ho-oh
  C:\\Python310\\python.exe tools/find_shiny_frame.py --tid 12345 --sid 54321 --target ho-oh --nature adamant
  C:\\Python310\\python.exe tools/find_shiny_frame.py --tid 12345 --sid 54321 --target ho-oh --max-frame 200000

The --profile flag reads TID/SID from data/hunt_profile.json (saved by find_sid.py --save).
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rng.frlg_rng import find_shiny_frames, frame_to_jitter_ms, GBA_FRAME_MS, NATURES

# ── Base frame offsets per target ────────────────────────────────────────────
# These represent the approximate number of PRNG frames consumed from the
# moment you press START on the title screen until the encounter PID is
# generated.  They must be calibrated empirically for each target.
#
# Calibration method:
#   1. Find your SID from a known shiny (find_sid.py gives you the frame number)
#   2. You know the START jitter you used (from hunt.log)
#   3. base_offset = frame - round(jitter_ms / 16.7427)
#
# These are initial estimates.  The --calibrate flag can refine them.
BASE_FRAME_OFFSETS = {
    "mewtwo":     2000,
    "zapdos":     1800,
    "articuno":   1800,
    "moltres":    1800,
    "ho-oh":      2000,
    "lugia":      2000,
    "deoxys":     1800,
    "bulbasaur":  1200,
    "charmander": 1200,
    "squirtle":   1200,
}

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "hunt_profile.json")


def load_profile() -> dict:
    path = os.path.normpath(PROFILE_PATH)
    if not os.path.exists(path):
        print(f"  Profile not found at {path}")
        print("  Run find_sid.py --save first, or provide --tid and --sid manually.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def iv_total(ivs: dict) -> int:
    return sum(ivs.values())


def main():
    parser = argparse.ArgumentParser(description="Find shiny PRNG frames for FRLG RNG manipulation")
    parser.add_argument("--tid", type=int, help="Trainer ID")
    parser.add_argument("--sid", type=int, help="Secret ID")
    parser.add_argument("--profile", action="store_true",
                        help="Read TID/SID from data/hunt_profile.json")
    parser.add_argument("--target", required=True,
                        help="Target Pokemon (mewtwo, ho-oh, lugia, deoxys, zapdos, etc.)")
    parser.add_argument("--nature", default=None,
                        help="Filter by nature (e.g. adamant, jolly, timid)")
    parser.add_argument("--min-frame", type=int, default=0)
    parser.add_argument("--max-frame", type=int, default=100000,
                        help="Maximum frame to search (default: 100000)")
    parser.add_argument("--base-offset", type=int, default=None,
                        help="Override the base frame offset for this target")
    parser.add_argument("--top", type=int, default=20,
                        help="Show top N results sorted by IV total (default: 20)")
    args = parser.parse_args()

    if args.profile:
        profile = load_profile()
        tid = profile["tid"]
        sid = profile["sid"]
        print(f"  Loaded profile: TID={tid}, SID={sid}")
    elif args.tid is not None and args.sid is not None:
        tid = args.tid
        sid = args.sid
    else:
        print("  Provide --tid and --sid, or use --profile to load from hunt_profile.json")
        sys.exit(1)

    target = args.target.lower()
    base_offset = args.base_offset or BASE_FRAME_OFFSETS.get(target, 2000)

    if args.nature and args.nature.capitalize() not in NATURES:
        print(f"  Unknown nature: {args.nature}")
        print(f"  Valid natures: {', '.join(NATURES)}")
        sys.exit(1)

    print()
    print("=" * 70)
    print("  FRLG SHINY FRAME FINDER")
    print("=" * 70)
    print(f"  TID:            {tid}")
    print(f"  SID:            {sid}")
    print(f"  Target:         {target.title()}")
    print(f"  Nature filter:  {args.nature or 'any'}")
    print(f"  Frame range:    {args.min_frame} – {args.max_frame}")
    print(f"  Base offset:    {base_offset} frames (title→encounter)")
    print(f"  GBA frame:      {GBA_FRAME_MS:.4f} ms")
    print()
    print("  Searching...")

    results = find_shiny_frames(
        tid=tid,
        sid=sid,
        frame_min=args.min_frame,
        frame_max=args.max_frame,
        nature_filter=args.nature,
    )

    if not results:
        print(f"\n  No shiny frames found in range {args.min_frame}–{args.max_frame}.")
        if args.nature:
            print(f"  Try removing the --nature filter or increasing --max-frame.")
        else:
            print(f"  Try increasing --max-frame (e.g. --max-frame 500000).")
        return

    # Sort by IV total descending
    results.sort(key=lambda r: iv_total(r["ivs"]), reverse=True)
    show = results[:args.top]

    print(f"\n  Found {len(results)} shiny frames total. Showing top {len(show)} by IV total:\n")
    print(f"  {'Frame':>7}  {'PID':>10}  {'Nature':<10}  {'HP':>2} {'At':>2} {'Df':>2} {'SA':>2} {'SD':>2} {'Sp':>2}  {'Total':>3}  {'Jitter':>8}  {'Reachable'}")
    print(f"  {'─'*7}  {'─'*10}  {'─'*10}  {'─'*2} {'─'*2} {'─'*2} {'─'*2} {'─'*2} {'─'*2}  {'─'*3}  {'─'*8}  {'─'*9}")

    for r in show:
        iv = r["ivs"]
        total = iv_total(iv)
        jitter = frame_to_jitter_ms(r["frame"], base_offset)
        reachable = "YES" if 0 <= jitter <= 5000 else "no (out of range)"

        print(
            f"  {r['frame']:>7}  {r['pid']:>10}  {r['nature']:<10}"
            f"  {iv['hp']:>2} {iv['atk']:>2} {iv['def']:>2} {iv['spa']:>2} {iv['spd']:>2} {iv['spe']:>2}"
            f"  {total:>3}  {jitter:>7.1f}ms  {reachable}"
        )

    # Show the best reachable frame
    reachable = [r for r in results if 0 <= frame_to_jitter_ms(r["frame"], base_offset) <= 5000]
    if reachable:
        reachable.sort(key=lambda r: iv_total(r["ivs"]), reverse=True)
        best = reachable[0]
        iv = best["ivs"]
        jitter = frame_to_jitter_ms(best["frame"], base_offset)
        print(f"\n  ★ BEST REACHABLE FRAME:")
        print(f"    Frame {best['frame']}, PID={best['pid']}, Nature={best['nature']}")
        print(f"    IVs: HP={iv['hp']} Atk={iv['atk']} Def={iv['def']} SpA={iv['spa']} SpD={iv['spd']} Spe={iv['spe']} (total={iv_total(iv)})")
        print(f"    START jitter: {jitter:.1f}ms")
        print(f"\n  To use this frame with the RNG hunt mode:")
        print(f"    python tools/run_hunt.py --target {target} --mode rng --start-ms {int(round(jitter))} --continue-ms 0")
    else:
        print(f"\n  ⚠ No reachable frames (jitter 0-5000ms) found.")
        print(f"  Try adjusting --base-offset or increasing --max-frame.")

    # Save results to JSON for reference
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", f"shiny_frames_{target}.json")
    out_path = os.path.normpath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "tid": tid,
            "sid": sid,
            "target": target,
            "base_offset": base_offset,
            "nature_filter": args.nature,
            "frame_range": [args.min_frame, args.max_frame],
            "total_found": len(results),
            "frames": results,
        }, f, indent=2)
    print(f"\n  Full results saved to {out_path}")
    print()


if __name__ == "__main__":
    main()
