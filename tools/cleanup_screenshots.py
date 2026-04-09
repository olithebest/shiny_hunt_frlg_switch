"""
Screenshot Cleanup Tool
=======================
Removes all non-shiny encounter screenshots and debug images to reclaim disk space.

What gets KEPT:
  - encounters/*_crop_SHINY.png  (shiny encounter crops)
  - encounters/*_full.png        (matching full frame for each shiny crop)
  - tools/screenshots/shiny_*.png (shiny celebration screenshots)
  - detection_tests/              (test output — small, useful)
  - sid_debug/                    (SID calculation debug — small, useful)

What gets DELETED:
  - encounters/*_crop_normal.png  (every non-shiny encounter crop)
  - encounters/*_full.png         (full frames without a matching shiny crop)
  - encounters/*_FAKE_SHINY*      (test artifacts)
  - color_checks/*                (debug images from confirm_shiny_by_color)
  - hunt_start.png, ref_sprite_crop.png (transient startup images)

Usage:
  python tools/cleanup_screenshots.py              # dry run — shows what would be deleted
  python tools/cleanup_screenshots.py --execute    # actually deletes files
"""

import os
import re
import argparse


TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.join(TOOLS_DIR, "screenshots")
ENCOUNTERS_DIR = os.path.join(SCREENSHOTS_DIR, "encounters")
COLOR_CHECKS_DIR = os.path.join(SCREENSHOTS_DIR, "color_checks")

# Root-level files to always keep
ROOT_KEEP_PATTERNS = [
    re.compile(r"^shiny_.*\.png$"),  # shiny celebration screenshots
]

# Directories to never touch
PROTECTED_DIRS = {"detection_tests", "sid_debug"}


def find_shiny_encounters(enc_dir: str) -> set:
    """Find encounter numbers that have a SHINY crop — these get preserved."""
    shiny_numbers = set()
    if not os.path.isdir(enc_dir):
        return shiny_numbers

    pattern = re.compile(r"^(.+?)_(\d+)_crop_SHINY\.png$")
    for name in os.listdir(enc_dir):
        m = pattern.match(name)
        if m:
            target = m.group(1)
            num = m.group(2)
            shiny_numbers.add((target, num))

    return shiny_numbers


def plan_encounter_cleanup(enc_dir: str) -> tuple:
    """Plan which encounter files to keep vs delete.

    Returns (keep_list, delete_list) of absolute paths.
    """
    keep = []
    delete = []

    if not os.path.isdir(enc_dir):
        return keep, delete

    shiny_encounters = find_shiny_encounters(enc_dir)

    for name in sorted(os.listdir(enc_dir)):
        path = os.path.join(enc_dir, name)
        if not os.path.isfile(path):
            continue

        # Check if this file belongs to a shiny encounter
        # Match: {target}_{number}_full.png or {target}_{number}_crop_SHINY.png
        m = re.match(r"^(.+?)_(\d+)_(full|crop_.+)\.png$", name)
        if m:
            target, num, suffix = m.group(1), m.group(2), m.group(3)
            if (target, num) in shiny_encounters:
                keep.append(path)
                continue

        # Everything else gets deleted
        delete.append(path)

    return keep, delete


def plan_color_checks_cleanup(cc_dir: str) -> tuple:
    """All color check debug images get deleted."""
    keep = []
    delete = []
    if not os.path.isdir(cc_dir):
        return keep, delete
    for name in os.listdir(cc_dir):
        path = os.path.join(cc_dir, name)
        if os.path.isfile(path):
            delete.append(path)
    return keep, delete


def plan_root_cleanup(screenshots_dir: str) -> tuple:
    """Clean root-level transient files, keep shiny screenshots."""
    keep = []
    delete = []
    for name in os.listdir(screenshots_dir):
        path = os.path.join(screenshots_dir, name)
        if not os.path.isfile(path):
            continue
        if any(p.match(name) for p in ROOT_KEEP_PATTERNS):
            keep.append(path)
        else:
            delete.append(path)
    return keep, delete


def format_size(bytes_count: int) -> str:
    if bytes_count >= 1024 * 1024 * 1024:
        return f"{bytes_count / (1024**3):.1f} GB"
    if bytes_count >= 1024 * 1024:
        return f"{bytes_count / (1024**2):.1f} MB"
    if bytes_count >= 1024:
        return f"{bytes_count / 1024:.1f} KB"
    return f"{bytes_count} B"


def total_size(paths: list) -> int:
    return sum(os.path.getsize(p) for p in paths if os.path.isfile(p))


def main():
    parser = argparse.ArgumentParser(description="Clean up non-shiny screenshots")
    parser.add_argument("--execute", action="store_true",
                        help="Actually delete files (default is dry run)")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  Screenshot Cleanup Tool")
    print("  Mode:", "EXECUTE — files will be deleted!" if args.execute else "DRY RUN — nothing will be deleted")
    print("=" * 60)
    print()

    all_keep = []
    all_delete = []

    # 1. Encounters
    enc_keep, enc_delete = plan_encounter_cleanup(ENCOUNTERS_DIR)
    all_keep.extend(enc_keep)
    all_delete.extend(enc_delete)

    shiny_encounters = find_shiny_encounters(ENCOUNTERS_DIR)
    print(f"  encounters/")
    print(f"    Shiny encounters found: {len(shiny_encounters)}")
    for target, num in sorted(shiny_encounters):
        print(f"      {target} #{num}")
    print(f"    Keep:   {len(enc_keep)} files ({format_size(total_size(enc_keep))})")
    print(f"    Delete: {len(enc_delete)} files ({format_size(total_size(enc_delete))})")
    print()

    # 2. Color checks
    cc_keep, cc_delete = plan_color_checks_cleanup(COLOR_CHECKS_DIR)
    all_keep.extend(cc_keep)
    all_delete.extend(cc_delete)

    print(f"  color_checks/")
    print(f"    Delete: {len(cc_delete)} files ({format_size(total_size(cc_delete))})")
    print()

    # 3. Root screenshots
    root_keep, root_delete = plan_root_cleanup(SCREENSHOTS_DIR)
    all_keep.extend(root_keep)
    all_delete.extend(root_delete)

    if root_keep:
        print(f"  Root screenshots kept:")
        for p in root_keep:
            print(f"    {os.path.basename(p)}")
    if root_delete:
        print(f"  Root screenshots deleted:")
        for p in root_delete:
            print(f"    {os.path.basename(p)}")
    print()

    # 4. Protected dirs
    for d in PROTECTED_DIRS:
        dpath = os.path.join(SCREENSHOTS_DIR, d)
        if os.path.isdir(dpath):
            count = len(os.listdir(dpath))
            print(f"  {d}/ — {count} files (protected, not touched)")
    print()

    # Summary
    delete_size = total_size(all_delete)
    keep_size = total_size(all_keep)

    print("-" * 60)
    print(f"  TOTAL DELETE: {len(all_delete)} files ({format_size(delete_size)})")
    print(f"  TOTAL KEEP:   {len(all_keep)} files ({format_size(keep_size)})")
    print("-" * 60)

    if not all_delete:
        print("\n  Nothing to clean up!")
        return

    if not args.execute:
        print("\n  This was a DRY RUN. To actually delete, run:")
        print("    python tools/cleanup_screenshots.py --execute")
        return

    # Execute deletion
    print(f"\n  Deleting {len(all_delete)} files...")
    deleted = 0
    errors = 0
    for path in all_delete:
        try:
            os.remove(path)
            deleted += 1
        except OSError as e:
            print(f"    ERROR: {e}")
            errors += 1

    print(f"\n  Done! Deleted {deleted} files, freed {format_size(delete_size)}.")
    if errors:
        print(f"  {errors} files could not be deleted.")


if __name__ == "__main__":
    main()
