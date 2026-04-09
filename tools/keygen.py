#!/usr/bin/env python3
"""
keygen.py — License key generator for Shiny Hunter FRLG
=========================================================
Run this privately (never ship this script to customers).

Usage:
    python tools/keygen.py --hunts mewtwo lugia --email buyer@example.com
    python tools/keygen.py --hunts mewtwo --email buyer@example.com --secret "your-secret"
    python tools/keygen.py --all --email buyer@example.com

Environment variable:
    SHINY_HUNTER_SECRET  — master signing secret (or pass via --secret)
"""

import sys
import os
import argparse
from datetime import date

# Make project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.licensing.license_manager import generate_key, validate_key, HUNT_CATALOGUE


def main():
    parser = argparse.ArgumentParser(
        description="Generate a signed license key for Shiny Hunter FRLG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/keygen.py --hunts mewtwo --email buyer@example.com
  python tools/keygen.py --hunts mewtwo lugia ho-oh --email buyer@example.com
  python tools/keygen.py --all --email buyer@example.com
        """,
    )
    parser.add_argument(
        "--hunts", nargs="+", choices=list(HUNT_CATALOGUE.keys()),
        metavar="HUNT", help="Hunt ID(s) to unlock"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Unlock all available hunts (e.g. for a bundle sale)"
    )
    parser.add_argument(
        "--email", required=True,
        help="Buyer email address (embedded in key for traceability)"
    )
    parser.add_argument(
        "--issued", default=str(date.today()),
        help="Issue date (ISO format, default: today)"
    )
    parser.add_argument(
        "--secret", default=None,
        help="Override master secret (also readable from SHINY_HUNTER_SECRET env var)"
    )
    args = parser.parse_args()

    if args.secret:
        import src.licensing.license_manager as lm
        lm.MASTER_SECRET = args.secret.encode()

    if args.all:
        hunts = list(HUNT_CATALOGUE.keys())
    elif args.hunts:
        hunts = args.hunts
    else:
        parser.error("Specify --hunts or --all")

    key = generate_key(hunts=hunts, email=args.email, issued=args.issued)

    # Self-validate before printing
    verified = validate_key(key)
    if not verified:
        print("ERROR: generated key failed self-validation!", file=sys.stderr)
        sys.exit(1)

    print()
    print("=" * 60)
    print("  LICENSE KEY (send this to the customer)")
    print("=" * 60)
    print(f"  {key}")
    print("=" * 60)
    print(f"  Hunts unlocked : {', '.join(h.title() for h in verified)}")
    print(f"  Buyer email    : {args.email}")
    print(f"  Issued         : {args.issued}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
