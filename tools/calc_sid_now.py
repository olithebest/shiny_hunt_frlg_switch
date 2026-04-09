"""
Calculate SID directly from screenshot data.
TID=59556, Impish shiny Mewtwo Lv70
Stats: HP=236, Atk=163, Def=161, SpAtk=214, SpDef=149, Spe=190
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tools.find_sid import search_frames, calc_iv_from_stat, BASE_STATS, nature_multiplier

tid = 59556
species = "mewtwo"
level = 70
nature = "Impish"
stats = [236, 163, 161, 214, 149, 190]
bases = BASE_STATS[species]  # (106, 110, 90, 154, 90, 130)

labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
is_hp = [True, False, False, False, False, False]

print("=" * 60)
print("  SID Calculation from Shiny Mewtwo")
print("=" * 60)
print(f"  TID:     {tid}")
print(f"  Nature:  {nature}")
print(f"  Stats:   {dict(zip(labels, stats))}")
print()

iv_candidates = []
for i, (stat, base, label) in enumerate(zip(stats, bases, labels)):
    hp = is_hp[i]
    mult = nature_multiplier(nature, i)
    ivs = calc_iv_from_stat(stat, base, level, mult, hp)
    print(f"  {label}: stat={stat}, base={base}, nat_mult={mult} -> IVs={ivs}")
    iv_candidates.append(ivs)

print()
print("  Searching PRNG frames 0-100000...")
results = search_frames(
    tid=tid,
    nature_name=nature,
    iv_sets=iv_candidates,
    is_shiny=True,
    frame_min=0,
    frame_max=100000,
)

print(f"  Found {len(results)} matching frame(s)")
print()
for r in results:
    ivs = r["ivs"]
    print(f"  Frame {r['frame']:>6}  PID={r['pid']}  Nature={r['nature']}")
    print(f"    IVs: HP={ivs[0]} Atk={ivs[1]} Def={ivs[2]} SpA={ivs[3]} SpD={ivs[4]} Spe={ivs[5]}")
    print(f"    SID candidates: {r['sid_candidates']}")
    print()

if results:
    best = results[0]
    print("=" * 60)
    print(f"  YOUR SID is one of: {best['sid_candidates']}")
    print(f"  Most likely SID:    {best['sid_candidates'][0]}")
    print("=" * 60)

    # Save to profile
    profile_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "hunt_profile.json"))
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)
    profile = {"tid": tid}
    # Save the first SID candidate
    profile["sid"] = best["sid_candidates"][0]
    profile["sid_candidates"] = best["sid_candidates"]
    profile["source_frame"] = best["frame"]
    profile["source_pid"] = best["pid"]
    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)
    print(f"\n  Saved to {profile_path}")
    print(f"  (If Ho-Oh RNG doesn't work, try other SID candidates)")
