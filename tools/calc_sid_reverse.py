"""
Reverse SID Calculator — works backwards from IVs to find SID.
No frame search needed — directly reconstructs the PID from IV constraints.

Method 1: seed → r1(PID_lo) → r2(PID_hi) → r3(IVs1) → r4(IVs2)
We know r3 and r4 from the IVs. We brute-force the lower 16 bits of seed3,
then reverse the PRNG to find r1 and r2 (the PID), then derive SID.
"""
import sys, os, json, itertools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tools.find_sid import calc_iv_from_stat, BASE_STATS, nature_multiplier, NATURES

# FRLG PRNG constants
A = 0x41C64E6D
C = 0x6073
MASK = 0xFFFFFFFF

# Reverse PRNG: multiplicative inverse of A mod 2^32
A_INV = 0xEEB9EB65
C_INV = (-A_INV * C) & MASK  # additive constant for reverse step


def prng_advance(seed):
    return (A * seed + C) & MASK


def prng_reverse(seed):
    return (A_INV * seed + C_INV) & MASK


def reverse_sid_search(tid, nature_name, iv_candidates):
    """
    Given TID, nature, and IV candidates per stat, find all valid PIDs
    by reversing from the IV PRNG calls.

    Returns list of dicts: {pid, ivs, sid_candidates, nature}
    """
    nature_idx = NATURES.index(nature_name)

    # Build all possible (r3, r4) combinations
    # r3 = hp_iv | (atk_iv << 5) | (def_iv << 10)
    # r4 = spa_iv | (spd_iv << 5) | (spe_iv << 10)
    hp_ivs, atk_ivs, def_ivs, spa_ivs, spd_ivs, spe_ivs = iv_candidates

    r3_options = set()
    for hp, atk, df in itertools.product(hp_ivs, atk_ivs, def_ivs):
        r3_options.add((hp | (atk << 5) | (df << 10), (hp, atk, df)))

    r4_options = set()
    for spa, spd, spe in itertools.product(spa_ivs, spd_ivs, spe_ivs):
        r4_options.add((spa | (spd << 5) | (spe << 10), (spa, spd, spe)))

    results = []

    for (r3_val, (hp, atk, df)), (r4_val, (spa, spd, spe)) in itertools.product(r3_options, r4_options):
        # Brute-force lower 16 bits of seed3
        for lo in range(65536):
            seed3 = (r3_val << 16) | lo
            seed4 = prng_advance(seed3)

            if (seed4 >> 16) != r4_val:
                continue

            # Found a valid seed3! Reverse to get seed2, seed1, seed0
            seed2 = prng_reverse(seed3)
            seed1 = prng_reverse(seed2)

            r2 = seed2 >> 16   # PID high
            r1 = seed1 >> 16   # PID low

            pid = (r2 << 16) | r1

            # Check nature
            if pid % 25 != nature_idx:
                continue

            # Valid PID! Compute SID candidates
            xor_val = tid ^ r2 ^ r1
            sid_candidates = [xor_val ^ x for x in range(8)]

            results.append({
                "pid": f"{pid:08X}",
                "pid_int": pid,
                "ivs": {"hp": hp, "atk": atk, "def": df, "spa": spa, "spd": spd, "spe": spe},
                "sid_candidates": sid_candidates,
                "nature": nature_name,
                "xor_val": xor_val,
            })

    return results


# ── Your shiny Mewtwo data (from screenshots) ──────────────────────
tid = 59556
species = "mewtwo"
level = 70
nature = "Impish"
stats = [236, 163, 161, 214, 149, 190]
bases = BASE_STATS[species]

labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
is_hp = [True, False, False, False, False, False]

print("=" * 60)
print("  REVERSE SID CALCULATOR")
print("=" * 60)
print(f"  TID:     {tid}")
print(f"  Species: {species.title()} (Level {level})")
print(f"  Nature:  {nature}")
print(f"  Stats:   {dict(zip(labels, stats))}")
print()

# Calculate IV candidates
iv_candidates = []
for i, (stat, base, label) in enumerate(zip(stats, bases, labels)):
    mult = nature_multiplier(nature, i)
    ivs = calc_iv_from_stat(stat, base, level, mult, is_hp[i])
    print(f"  {label}: stat={stat}, base={base}, mult={mult} -> IVs={ivs}")
    iv_candidates.append(ivs)

total_combos = 1
for ivs in iv_candidates:
    total_combos *= len(ivs)
print(f"\n  IV combinations to check: {total_combos}")
print(f"  Total PRNG iterations: {total_combos * 65536:,}")
print()
print("  Searching (reverse from IVs)...")

results = reverse_sid_search(tid, nature, iv_candidates)

print(f"  Found {len(results)} matching PID(s)")
print()

if not results:
    print("  No matches found — stats or nature may be incorrect.")
else:
    # Filter to only shiny results (xor_val < 8 or close)
    shiny_results = [r for r in results if any(
        (tid ^ sid ^ (r["pid_int"] >> 16) ^ (r["pid_int"] & 0xFFFF)) < 8
        for sid in r["sid_candidates"]
    )]

    for r in results:
        iv = r["ivs"]
        print(f"  PID: {r['pid']}  Nature: {r['nature']}")
        print(f"  IVs: HP={iv['hp']} Atk={iv['atk']} Def={iv['def']} SpA={iv['spa']} SpD={iv['spd']} Spe={iv['spe']}")
        print(f"  SID candidates: {r['sid_candidates']}")
        # Show which SID actually makes it shiny
        for sid in r["sid_candidates"]:
            xor = tid ^ sid ^ (r["pid_int"] >> 16) ^ (r["pid_int"] & 0xFFFF)
            if xor < 8:
                print(f"  ★ SID={sid} → shiny (XOR={xor})")
        print()

    # Collect all unique SID values that produce a shiny
    all_sids = set()
    for r in results:
        for sid in r["sid_candidates"]:
            xor = tid ^ sid ^ (r["pid_int"] >> 16) ^ (r["pid_int"] & 0xFFFF)
            if xor < 8:
                all_sids.add(sid)

    print("=" * 60)
    print(f"  POSSIBLE SIDs (that make this Mewtwo shiny):")
    for sid in sorted(all_sids):
        print(f"    SID = {sid}")
    print("=" * 60)

    # Save to profile
    if all_sids:
        sid_list = sorted(all_sids)
        profile = {
            "tid": tid,
            "sid": sid_list[0],
            "sid_candidates": sid_list,
            "source_pokemon": species,
            "source_nature": nature,
            "source_stats": dict(zip(labels, stats)),
        }
        profile_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "data", "hunt_profile.json"
        ))
        os.makedirs(os.path.dirname(profile_path), exist_ok=True)
        with open(profile_path, "w") as f:
            json.dump(profile, f, indent=2)
        print(f"\n  Saved to {profile_path}")
