#!/usr/bin/env python3
"""
build_release.py — Package a clean distributable zip for buyers
================================================================
Creates  dist/shiny-hunter-frlg.zip  with all the code but WITHOUT:

  - Nintendo IP assets (sprites, reference images, training screenshots)
  - Your personal data (TID/SID profile, hunt progress, licenses)
  - Developer artifacts (__pycache__, .env, .git, logs, *.bak)
  - Server-only files buyers don't need (Dockerfile, render.yaml, Procfile)

Usage:
    python tools/build_release.py
    python tools/build_release.py --output my_custom_name.zip
"""

import argparse
import os
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Folders/files to exclude entirely (relative to project root)
# ---------------------------------------------------------------------------
EXCLUDE_DIRS = {
    # Nintendo game assets — COPYRIGHT RISK, never ship these
    "data/sprites",
    "data/reference_normals",
    "data/reference_shinies",
    "data/training_pairs",
    "tools/screenshots",

    # Developer/server files buyers don't need
    ".git",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
}

EXCLUDE_FILES = {
    # Secrets
    ".env",

    # Personal calibration / progress data (buyer configures their own)
    "data/hunt_profile.json",
    "data/hunt_progress.json",
    "data/licenses.json",
    "data/hunt.log",

    # Server deployment files (Render/Docker — not needed by buyers)
    "Dockerfile",
    "docker-compose.yml",
    "render.yaml",
    "Procfile",
    "wsgi.py",
    "requirements-webhook.txt",

    # This build script itself
    "tools/build_release.py",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".bak",
    ".log",
    ".DS_Store",
}

# ---------------------------------------------------------------------------
# Placeholder dirs to create inside the zip so the app doesn't crash on
# first run looking for these directories.
# These will contain only a README.txt explaining they're populated at runtime.
# ---------------------------------------------------------------------------
PLACEHOLDER_DIRS = [
    "data/sprites/frlg/normal",
    "data/sprites/frlg/shiny",
    "data/reference_normals",
    "data/reference_shinies",
    "data/training_pairs",
    "tools/screenshots/encounters",
    "tools/screenshots/color_checks",
    "tools/screenshots/detection_tests",
    "tools/screenshots/sid_debug",
]

PLACEHOLDER_README = """\
This folder is populated automatically when you run the tool.
No manual action needed — it will be created/filled at runtime.
"""


def should_exclude(rel_path: str) -> bool:
    """Return True if this path should be left out of the zip."""
    parts = Path(rel_path).parts

    # Check excluded dir names anywhere in the path
    for part in parts:
        if part in {"__pycache__", ".git", ".pytest_cache", ".venv", "venv", "env"}:
            return True

    # Check top-level dir prefixes
    rel_posix = Path(rel_path).as_posix()
    for excl in EXCLUDE_DIRS:
        if rel_posix == excl or rel_posix.startswith(excl + "/"):
            return True

    # Check exact file matches
    if rel_posix in EXCLUDE_FILES:
        return True

    # Check extensions
    if Path(rel_path).suffix.lower() in EXCLUDE_EXTENSIONS:
        return True

    return False


def build_zip(output_path: Path, project_root: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    included = []
    excluded = []

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Walk every file in the project
        for abs_path in sorted(project_root.rglob("*")):
            if not abs_path.is_file():
                continue

            rel = abs_path.relative_to(project_root)
            rel_str = rel.as_posix()

            if should_exclude(rel_str):
                excluded.append(rel_str)
                continue

            zf.write(abs_path, rel_str)
            included.append(rel_str)

        # Add placeholder README files for runtime-populated dirs
        for placeholder_dir in PLACEHOLDER_DIRS:
            arc_name = f"{placeholder_dir}/README.txt"
            zf.writestr(arc_name, PLACEHOLDER_README)

        # Add a default empty hunt_profile.json so setup.bat doesn't fail
        default_profile = '{"tid": null, "sid": null}\n'
        zf.writestr("data/hunt_profile.json", default_profile)

        # Add a default empty hunt_progress.json
        default_progress = '{}\n'
        zf.writestr("data/hunt_progress.json", default_progress)

    return included, excluded


def main():
    parser = argparse.ArgumentParser(description="Build a clean release zip")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output zip filename (default: dist/shiny-hunter-frlg.zip)"
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    dist_dir = project_root / "dist"

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = dist_dir / output_path
    else:
        output_path = dist_dir / "shiny-hunter-frlg.zip"

    print(f"Building release zip...")
    print(f"  Source:  {project_root}")
    print(f"  Output:  {output_path}")
    print()

    included, excluded = build_zip(output_path, project_root)

    print(f"INCLUDED ({len(included)} files):")
    for f in included:
        print(f"  + {f}")

    print()
    print(f"EXCLUDED ({len(excluded)} files — Nintendo assets, personal data, dev files):")
    for f in excluded:
        print(f"  - {f}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print()
    print(f"Done! {output_path.name}  ({size_mb:.2f} MB)")
    print(f"Upload this file to your itch.io product page.")


if __name__ == "__main__":
    main()
