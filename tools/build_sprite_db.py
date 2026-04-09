"""
Download all 386 Gen-III FRLG sprites (normal + shiny) from PokeAPI
and auto-generate the complete palette & color-profile databases.

Usage:
    python tools/build_sprite_db.py            # download + analyze + generate
    python tools/build_sprite_db.py --skip-dl   # skip download, re-analyze existing sprites
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import cv2
import numpy as np
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SPRITE_DIR = BASE_DIR / "data" / "sprites" / "frlg"
NORMAL_DIR = SPRITE_DIR / "normal"
SHINY_DIR = SPRITE_DIR / "shiny"
OUTPUT_DIR = BASE_DIR / "src" / "detection"

# PokeAPI raw GitHub URLs — FRLG for Gen I (1-151), Emerald for Gen II-III (152-386)
FRLG_NORMAL_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/firered-leafgreen/{dex}.png"
FRLG_SHINY_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/firered-leafgreen/shiny/{dex}.png"
EMERALD_NORMAL_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/emerald/{dex}.png"
EMERALD_SHINY_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/emerald/shiny/{dex}.png"

# Gen I-III Pokémon names (dex 1-386)
POKEMON_NAMES = {
    1: "bulbasaur", 2: "ivysaur", 3: "venusaur", 4: "charmander", 5: "charmeleon",
    6: "charizard", 7: "squirtle", 8: "wartortle", 9: "blastoise", 10: "caterpie",
    11: "metapod", 12: "butterfree", 13: "weedle", 14: "kakuna", 15: "beedrill",
    16: "pidgey", 17: "pidgeotto", 18: "pidgeot", 19: "rattata", 20: "raticate",
    21: "spearow", 22: "fearow", 23: "ekans", 24: "arbok", 25: "pikachu",
    26: "raichu", 27: "sandshrew", 28: "sandslash", 29: "nidoran_f", 30: "nidorina",
    31: "nidoqueen", 32: "nidoran_m", 33: "nidorino", 34: "nidoking", 35: "clefairy",
    36: "clefable", 37: "vulpix", 38: "ninetales", 39: "jigglypuff", 40: "wigglytuff",
    41: "zubat", 42: "golbat", 43: "oddish", 44: "gloom", 45: "vileplume",
    46: "paras", 47: "parasect", 48: "venonat", 49: "venomoth", 50: "diglett",
    51: "dugtrio", 52: "meowth", 53: "persian", 54: "psyduck", 55: "golduck",
    56: "mankey", 57: "primeape", 58: "growlithe", 59: "arcanine", 60: "poliwag",
    61: "poliwhirl", 62: "poliwrath", 63: "abra", 64: "kadabra", 65: "alakazam",
    66: "machop", 67: "machoke", 68: "machamp", 69: "bellsprout", 70: "weepinbell",
    71: "victreebel", 72: "tentacool", 73: "tentacruel", 74: "geodude", 75: "graveler",
    76: "golem", 77: "ponyta", 78: "rapidash", 79: "slowpoke", 80: "slowbro",
    81: "magnemite", 82: "magneton", 83: "farfetchd", 84: "doduo", 85: "dodrio",
    86: "seel", 87: "dewgong", 88: "grimer", 89: "muk", 90: "shellder",
    91: "cloyster", 92: "gastly", 93: "haunter", 94: "gengar", 95: "onix",
    96: "drowzee", 97: "hypno", 98: "krabby", 99: "kingler", 100: "voltorb",
    101: "electrode", 102: "exeggcute", 103: "exeggutor", 104: "cubone", 105: "marowak",
    106: "hitmonlee", 107: "hitmonchan", 108: "lickitung", 109: "koffing", 110: "weezing",
    111: "rhyhorn", 112: "rhydon", 113: "chansey", 114: "tangela", 115: "kangaskhan",
    116: "horsea", 117: "seadra", 118: "goldeen", 119: "seaking", 120: "staryu",
    121: "starmie", 122: "mr_mime", 123: "scyther", 124: "jynx", 125: "electabuzz",
    126: "magmar", 127: "pinsir", 128: "tauros", 129: "magikarp", 130: "gyarados",
    131: "lapras", 132: "ditto", 133: "eevee", 134: "vaporeon", 135: "jolteon",
    136: "flareon", 137: "porygon", 138: "omanyte", 139: "omastar", 140: "kabuto",
    141: "kabutops", 142: "aerodactyl", 143: "snorlax", 144: "articuno", 145: "zapdos",
    146: "moltres", 147: "dratini", 148: "dragonair", 149: "dragonite", 150: "mewtwo",
    151: "mew",
    # Gen II
    152: "chikorita", 153: "bayleef", 154: "meganium", 155: "cyndaquil", 156: "quilava",
    157: "typhlosion", 158: "totodile", 159: "croconaw", 160: "feraligatr", 161: "sentret",
    162: "furret", 163: "hoothoot", 164: "noctowl", 165: "ledyba", 166: "ledian",
    167: "spinarak", 168: "ariados", 169: "crobat", 170: "chinchou", 171: "lanturn",
    172: "pichu", 173: "cleffa", 174: "igglybuff", 175: "togepi", 176: "togetic",
    177: "natu", 178: "xatu", 179: "mareep", 180: "flaaffy", 181: "ampharos",
    182: "bellossom", 183: "marill", 184: "azumarill", 185: "sudowoodo", 186: "politoed",
    187: "hoppip", 188: "skiploom", 189: "jumpluff", 190: "aipom", 191: "sunkern",
    192: "sunflora", 193: "yanma", 194: "wooper", 195: "quagsire", 196: "espeon",
    197: "umbreon", 198: "murkrow", 199: "slowking", 200: "misdreavus", 201: "unown",
    202: "wobbuffet", 203: "girafarig", 204: "pineco", 205: "forretress", 206: "dunsparce",
    207: "gligar", 208: "steelix", 209: "snubbull", 210: "granbull", 211: "qwilfish",
    212: "scizor", 213: "shuckle", 214: "heracross", 215: "sneasel", 216: "teddiursa",
    217: "ursaring", 218: "slugma", 219: "magcargo", 220: "swinub", 221: "piloswine",
    222: "corsola", 223: "remoraid", 224: "octillery", 225: "delibird", 226: "mantine",
    227: "skarmory", 228: "houndour", 229: "houndoom", 230: "kingdra", 231: "phanpy",
    232: "donphan", 233: "porygon2", 234: "stantler", 235: "smeargle", 236: "tyrogue",
    237: "hitmontop", 238: "smoochum", 239: "elekid", 240: "magby", 241: "miltank",
    242: "blissey", 243: "raikou", 244: "entei", 245: "suicune", 246: "larvitar",
    247: "pupitar", 248: "tyranitar", 249: "lugia", 250: "ho_oh", 251: "celebi",
    # Gen III
    252: "treecko", 253: "grovyle", 254: "sceptile", 255: "torchic", 256: "combusken",
    257: "blaziken", 258: "mudkip", 259: "marshtomp", 260: "swampert", 261: "poochyena",
    262: "mightyena", 263: "zigzagoon", 264: "linoone", 265: "wurmple", 266: "silcoon",
    267: "beautifly", 268: "cascoon", 269: "dustox", 270: "lotad", 271: "lombre",
    272: "ludicolo", 273: "seedot", 274: "nuzleaf", 275: "shiftry", 276: "taillow",
    277: "swellow", 278: "wingull", 279: "pelipper", 280: "ralts", 281: "kirlia",
    282: "gardevoir", 283: "surskit", 284: "masquerain", 285: "shroomish", 286: "breloom",
    287: "slakoth", 288: "vigoroth", 289: "slaking", 290: "nincada", 291: "ninjask",
    292: "shedinja", 293: "whismur", 294: "loudred", 295: "exploud", 296: "makuhita",
    297: "hariyama", 298: "azurill", 299: "nosepass", 300: "skitty", 301: "delcatty",
    302: "sableye", 303: "mawile", 304: "aron", 305: "lairon", 306: "aggron",
    307: "meditite", 308: "medicham", 309: "electrike", 310: "manectric", 311: "plusle",
    312: "minun", 313: "volbeat", 314: "illumise", 315: "roselia", 316: "gulpin",
    317: "swalot", 318: "carvanha", 319: "sharpedo", 320: "wailmer", 321: "wailord",
    322: "numel", 323: "camerupt", 324: "torkoal", 325: "spoink", 326: "grumpig",
    327: "spinda", 328: "trapinch", 329: "vibrava", 330: "flygon", 331: "cacnea",
    332: "cacturne", 333: "swablu", 334: "altaria", 335: "zangoose", 336: "seviper",
    337: "lunatone", 338: "solrock", 339: "barboach", 340: "whiscash", 341: "corphish",
    342: "crawdaunt", 343: "baltoy", 344: "claydol", 345: "lileep", 346: "cradily",
    347: "anorith", 348: "armaldo", 349: "feebas", 350: "milotic", 351: "castform",
    352: "kecleon", 353: "shuppet", 354: "banette", 355: "duskull", 356: "dusclops",
    357: "tropius", 358: "chimecho", 359: "absol", 360: "wynaut", 361: "snorunt",
    362: "glalie", 363: "spheal", 364: "sealeo", 365: "walrein", 366: "clamperl",
    367: "huntail", 368: "gorebyss", 369: "relicanth", 370: "luvdisc", 371: "bagon",
    372: "shelgon", 373: "salamence", 374: "beldum", 375: "metang", 376: "metagross",
    377: "regirock", 378: "regice", 379: "registeel", 380: "latias", 381: "latios",
    382: "kyogre", 383: "groudon", 384: "rayquaza", 385: "jirachi", 386: "deoxys",
}


def download_sprites(skip_existing: bool = True):
    """Download all 386 normal + shiny FRLG front sprites."""
    NORMAL_DIR.mkdir(parents=True, exist_ok=True)
    SHINY_DIR.mkdir(parents=True, exist_ok=True)

    total = len(POKEMON_NAMES)
    downloaded = 0
    skipped = 0
    failed = []

    for dex, name in sorted(POKEMON_NAMES.items()):
        # Use FRLG URLs for Gen I, Emerald for Gen II+
        if dex <= 151:
            normal_url_tpl = FRLG_NORMAL_URL
            shiny_url_tpl = FRLG_SHINY_URL
        else:
            normal_url_tpl = EMERALD_NORMAL_URL
            shiny_url_tpl = EMERALD_SHINY_URL

        for variant, url_tpl, out_dir in [
            ("normal", normal_url_tpl, NORMAL_DIR),
            ("shiny", shiny_url_tpl, SHINY_DIR),
        ]:
            out_path = out_dir / f"{dex:03d}_{name}.png"
            if skip_existing and out_path.exists():
                skipped += 1
                continue

            url = url_tpl.format(dex=dex)
            try:
                urllib.request.urlretrieve(url, str(out_path))
                downloaded += 1
            except urllib.error.HTTPError as e:
                print(f"  FAIL: {name} ({variant}) — HTTP {e.code}")
                failed.append((dex, name, variant))
            except Exception as e:
                print(f"  FAIL: {name} ({variant}) — {e}")
                failed.append((dex, name, variant))

            # Small delay to avoid rate limiting
            if downloaded % 20 == 0 and downloaded > 0:
                time.sleep(0.5)

        if (dex % 50 == 0) or dex == total:
            print(f"  [{dex}/{total}] downloaded={downloaded}, skipped={skipped}")

    print(f"\nDone: {downloaded} downloaded, {skipped} skipped, {len(failed)} failed")
    if failed:
        print("Failed:", failed)
    return failed


def analyze_sprite(path: str) -> dict:
    """Analyze a single sprite and return hue statistics."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None

    has_alpha = img.shape[2] == 4 if len(img.shape) > 2 else False

    bgr = img[:, :, :3]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    if has_alpha:
        alpha = img[:, :, 3]
        mask = alpha > 0
    else:
        mask = np.ones(img.shape[:2], dtype=bool)

    # Filter: saturation > 30 AND value > 30 to remove whites/blacks/grays
    color_mask = mask & (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 30)
    colored_px = int(color_mask.sum())

    if colored_px < 5:
        return {"colored_px": 0, "dominant_hue": None, "hue_range": None, "top_hues": []}

    hues = hsv[:, :, 0][color_mask]
    sats = hsv[:, :, 1][color_mask]

    hist = Counter(hues.tolist())
    top_hues = hist.most_common(10)
    dominant_hue = top_hues[0][0]

    # Find the main hue cluster (hues within ±15 of dominant)
    # Handle hue wrapping (0-179 in OpenCV)
    cluster_mask = np.zeros_like(hues, dtype=bool)
    for h_val, count in top_hues:
        diff = min(abs(h_val - dominant_hue), 180 - abs(h_val - dominant_hue))
        if diff <= 20:
            cluster_mask |= (hues == h_val)

    if cluster_mask.sum() > 0:
        cluster_hues = hues[cluster_mask]
        hue_min = int(np.percentile(cluster_hues, 5))
        hue_max = int(np.percentile(cluster_hues, 95))
    else:
        hue_min = hue_max = dominant_hue

    # Also get the secondary color cluster if exists
    remaining = [(h, c) for h, c in top_hues if min(abs(h - dominant_hue), 180 - abs(h - dominant_hue)) > 20]
    secondary_hue = remaining[0][0] if remaining else None

    return {
        "colored_px": colored_px,
        "dominant_hue": int(dominant_hue),
        "hue_range": (int(hue_min), int(hue_max)),
        "secondary_hue": int(secondary_hue) if secondary_hue is not None else None,
        "top_hues": [(int(h), int(c)) for h, c in top_hues[:5]],
        "median_sat": int(np.median(sats)),
    }


def analyze_all() -> dict:
    """Analyze all downloaded sprites and return comparison data."""
    results = {}
    total = len(POKEMON_NAMES)

    for dex, name in sorted(POKEMON_NAMES.items()):
        normal_path = NORMAL_DIR / f"{dex:03d}_{name}.png"
        shiny_path = SHINY_DIR / f"{dex:03d}_{name}.png"

        if not normal_path.exists() or not shiny_path.exists():
            continue

        normal_data = analyze_sprite(str(normal_path))
        shiny_data = analyze_sprite(str(shiny_path))

        if normal_data is None or shiny_data is None:
            continue

        # Calculate hue shift
        if normal_data["dominant_hue"] is not None and shiny_data["dominant_hue"] is not None:
            nh = normal_data["dominant_hue"]
            sh = shiny_data["dominant_hue"]
            hue_diff = min(abs(nh - sh), 180 - abs(nh - sh))
        else:
            hue_diff = 0

        # Classify subtlety
        subtle = hue_diff < 10

        results[name] = {
            "dex": dex,
            "normal": normal_data,
            "shiny": shiny_data,
            "hue_diff": hue_diff,
            "subtle": subtle,
        }

        if dex % 50 == 0 or dex == total:
            print(f"  Analyzed [{dex}/{total}]")

    return results


def generate_palette_db(analysis: dict) -> str:
    """Generate the complete frlg_palettes.py file from analysis data."""
    lines = []
    lines.append('"""')
    lines.append("Auto-generated FRLG palette database for all 386 Pokémon.")
    lines.append("Generated by tools/build_sprite_db.py from PokeAPI FRLG sprites.")
    lines.append("")
    lines.append("Each entry maps a species name to its normal/shiny hue ranges,")
    lines.append("enabling Tier-2 palette-based shiny detection.")
    lines.append('"""')
    lines.append("")
    lines.append("from dataclasses import dataclass, field")
    lines.append("from typing import Dict, Optional, Tuple")
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append("class PaletteEntry:")
    lines.append('    """HSV hue signature for a single Pokémon species."""')
    lines.append("    normal_hues: Tuple[int, int]   # (low, high) dominant hue range for normal form")
    lines.append("    shiny_hues: Tuple[int, int]    # (low, high) dominant hue range for shiny form")
    lines.append("    min_sat: int = 30              # minimum saturation to count as 'colored'")
    lines.append("    min_val: int = 30              # minimum value to count as 'colored'")
    lines.append("    subtle: bool = False           # True if hue shift is < 10 (needs sparkle confirmation)")
    lines.append('    description: str = ""')
    lines.append("")
    lines.append("")
    lines.append("# Complete database: 386 Pokémon")
    lines.append("FRLG_PALETTE_DB: Dict[str, PaletteEntry] = {")

    for name in sorted(analysis.keys(), key=lambda n: analysis[n]["dex"]):
        data = analysis[name]
        dex = data["dex"]
        nd = data["normal"]
        sd = data["shiny"]

        if nd["hue_range"] is None or sd["hue_range"] is None:
            # Not enough colored pixels — skip or use defaults
            lines.append(f'    # {dex:03d} {name}: insufficient colored pixels')
            continue

        # Expand hue ranges slightly for robustness (±5)
        n_lo = max(0, nd["hue_range"][0] - 5)
        n_hi = min(179, nd["hue_range"][1] + 5)
        s_lo = max(0, sd["hue_range"][0] - 5)
        s_hi = min(179, sd["hue_range"][1] + 5)

        subtle_str = "True" if data["subtle"] else "False"

        # For Mewtwo, keep the calibrated min_sat=120 from real game data
        min_sat = 120 if name == "mewtwo" else 30

        desc = f"H:{nd['dominant_hue']}->{sd['dominant_hue']} (diff={data['hue_diff']})"

        lines.append(f'    "{name}": PaletteEntry(')
        lines.append(f'        normal_hues=({n_lo}, {n_hi}),')
        lines.append(f'        shiny_hues=({s_lo}, {s_hi}),')
        if min_sat != 30:
            lines.append(f'        min_sat={min_sat},')
        if data["subtle"]:
            lines.append(f'        subtle={subtle_str},')
        lines.append(f'        description="{desc}",')
        lines.append(f'    ),  # #{dex:03d}')

    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append('def get_palette(species: str) -> Optional[PaletteEntry]:')
    lines.append('    """Look up the palette entry for a species (case-insensitive)."""')
    lines.append('    return FRLG_PALETTE_DB.get(species.lower().replace(" ", "_").replace("-", "_"))')
    lines.append("")
    lines.append("")
    lines.append('def classify_hue(species: str, dominant_hue: int) -> Optional[bool]:')
    lines.append('    """')
    lines.append("    Given the dominant hue from a battle frame, classify as shiny or not.")
    lines.append("    Returns True (shiny), False (normal), or None (inconclusive).")
    lines.append('    """')
    lines.append('    entry = get_palette(species)')
    lines.append('    if entry is None:')
    lines.append('        return None')
    lines.append("")
    lines.append("    in_normal = entry.normal_hues[0] <= dominant_hue <= entry.normal_hues[1]")
    lines.append("    in_shiny = entry.shiny_hues[0] <= dominant_hue <= entry.shiny_hues[1]")
    lines.append("")
    lines.append("    if in_shiny and not in_normal:")
    lines.append("        if entry.subtle:")
    lines.append("            return None  # too subtle, need sparkle confirmation")
    lines.append("        return True")
    lines.append("    if in_normal and not in_shiny:")
    lines.append("        return False")
    lines.append("    return None  # overlapping or out of range")
    lines.append("")

    return "\n".join(lines)


def generate_color_profiles(analysis: dict) -> str:
    """Generate the HSV body-color ranges for shiny_colors.py POKEMON_BODY_COLORS dict."""
    lines = []
    lines.append("# Auto-generated body-color profiles for Tier-4 detection")
    lines.append("# Generated by tools/build_sprite_db.py")
    lines.append("#")
    lines.append("# Format per entry:")
    lines.append('#   "species": {')
    lines.append('#       "shiny": {"lower": [H, S, V], "upper": [H, S, V]},')
    lines.append('#       "normal": {"lower": [H, S, V], "upper": [H, S, V]},')
    lines.append('#       "confirm_threshold": <int>,  # min pixels to confirm')
    lines.append("#   }")
    lines.append("")
    lines.append("POKEMON_BODY_COLORS = {")

    for name in sorted(analysis.keys(), key=lambda n: analysis[n]["dex"]):
        data = analysis[name]
        nd = data["normal"]
        sd = data["shiny"]

        if nd["hue_range"] is None or sd["hue_range"] is None:
            continue

        # Skip if too subtle (hue diff < 8) — color check won't help
        if data["hue_diff"] < 8:
            continue

        dex = data["dex"]

        # Build HSV ranges with some padding
        s_lo_h = max(0, sd["hue_range"][0] - 5)
        s_hi_h = min(179, sd["hue_range"][1] + 5)
        n_lo_h = max(0, nd["hue_range"][0] - 5)
        n_hi_h = min(179, nd["hue_range"][1] + 5)

        # Saturation/value: use 40 as lower bound, 255 as upper
        s_lower = 40
        v_lower = 80

        # Threshold: scale by colored pixel count
        threshold = max(50, min(sd["colored_px"] // 4, 500))

        lines.append(f'    "{name}": {{  # #{dex:03d} hue_diff={data["hue_diff"]}')
        lines.append(f'        "shiny": {{"lower": [{s_lo_h}, {s_lower}, {v_lower}], "upper": [{s_hi_h}, 255, 255]}},')
        lines.append(f'        "normal": {{"lower": [{n_lo_h}, {s_lower}, {v_lower}], "upper": [{n_hi_h}, 255, 255]}},')
        lines.append(f'        "confirm_threshold": {threshold},')
        lines.append(f"    }},")

    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def main():
    skip_dl = "--skip-dl" in sys.argv

    print("=" * 60)
    print("  FRLG Sprite Database Builder")
    print("=" * 60)
    print(f"  Sprites dir: {SPRITE_DIR}")
    print(f"  Total Pokémon: {len(POKEMON_NAMES)}")
    print()

    # Step 1: Download
    if not skip_dl:
        print("Step 1: Downloading sprites from PokeAPI...")
        failed = download_sprites()
        if failed:
            print(f"\nWARNING: {len(failed)} sprites failed to download.")
            print("Continuing with available sprites...\n")
    else:
        print("Step 1: Skipping download (--skip-dl)")
    print()

    # Step 2: Analyze
    print("Step 2: Analyzing sprite hue profiles...")
    analysis = analyze_all()
    print(f"  Analyzed {len(analysis)} Pokémon\n")

    # Save raw analysis as JSON for debugging
    json_path = SPRITE_DIR / "analysis.json"
    with open(json_path, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"  Raw analysis saved to {json_path}")

    # Step 3: Generate palette DB
    print("\nStep 3: Generating palette database...")
    palette_code = generate_palette_db(analysis)
    palette_path = OUTPUT_DIR / "frlg_palettes.py"

    # Backup existing
    if palette_path.exists():
        backup = palette_path.with_suffix(".py.bak")
        if backup.exists():
            backup.unlink()
        palette_path.rename(backup)
        print(f"  Backed up existing -> {backup.name}")

    palette_path.write_text(palette_code, encoding="utf-8")
    print(f"  Written: {palette_path}")

    # Step 4: Generate color profiles
    print("\nStep 4: Generating body-color profiles...")
    color_code = generate_color_profiles(analysis)
    color_output = SPRITE_DIR / "body_colors_generated.py"
    color_output.write_text(color_code, encoding="utf-8")
    print(f"  Written: {color_output}")
    print("  NOTE: Review and merge into src/detection/shiny_colors.py manually")

    # Step 5: Summary stats
    subtle_count = sum(1 for d in analysis.values() if d["subtle"])
    clear_count = len(analysis) - subtle_count
    no_color = sum(1 for d in analysis.values() if d["normal"]["colored_px"] == 0)

    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Total analyzed:    {len(analysis)}")
    print(f"  Clear hue shift:   {clear_count} (reliable palette detection)")
    print(f"  Subtle (< 10 diff):{subtle_count} (need sparkle confirmation)")
    print(f"  No colored pixels: {no_color}")
    print()

    # Show some examples of big vs subtle shifts
    sorted_by_diff = sorted(analysis.items(), key=lambda x: x[1]["hue_diff"], reverse=True)
    print("  Top 10 biggest hue shifts (easiest to detect):")
    for name, data in sorted_by_diff[:10]:
        n_hue = data["normal"]["dominant_hue"]
        s_hue = data["shiny"]["dominant_hue"]
        print(f"    #{data['dex']:03d} {name:15s}: {n_hue:3d} → {s_hue:3d} (diff={data['hue_diff']})")

    print("\n  Subtle shinies (hue diff < 10, need sparkle):")
    for name, data in sorted_by_diff:
        if data["subtle"]:
            n_hue = data["normal"]["dominant_hue"]
            s_hue = data["shiny"]["dominant_hue"]
            print(f"    #{data['dex']:03d} {name:15s}: {n_hue:3d} → {s_hue:3d} (diff={data['hue_diff']})")

    print("\nDone! The new frlg_palettes.py is ready to use.")


if __name__ == "__main__":
    main()
