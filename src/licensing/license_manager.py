"""
License Manager — Shiny Hunter FRLG
====================================
Validates signed license keys and manages which hunts are unlocked locally.

Key format (human-readable, URL-safe):
    <HUNT_CODE>-<12-char B32 payload>-<8-char B32 hmac>

Example:
    MEWTWO-BJLABCDE1234-ZXQRWVUT

The payload is a base32-encoded JSON blob:
    {"hunts": ["mewtwo"], "email": "user@example.com", "issued": "2026-04-08"}

The HMAC is computed with HMAC-SHA256 over the raw payload bytes, truncated to
8 chars of base32, using a secret master key (MASTER_SECRET in this file or an
environment variable SHINY_HUNTER_SECRET).

Security properties:
  - Keys are cryptographically signed → can't be forged without the secret
  - Each key is self-contained → works fully offline after entry
  - Keys are stored in data/licenses.json (plain list of valid key strings)
"""

import os
import json
import hmac
import hashlib
import base64
import re
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Master secret — change this to a long random string before distributing.
# Override at runtime via SHINY_HUNTER_SECRET env variable.
# ---------------------------------------------------------------------------
_DEFAULT_SECRET = "change-me-before-shipping-use-a-long-random-string-here"
MASTER_SECRET   = os.environ.get("SHINY_HUNTER_SECRET", _DEFAULT_SECRET).encode()

# ---------------------------------------------------------------------------
# Catalogue of all huntable Pokémon and their display info.
# Add new entries here as you build new hunt sequences.
# ---------------------------------------------------------------------------
HUNT_CATALOGUE = {
    "mewtwo":   {"display": "Mewtwo",   "price": "$2.00", "color": "#9B59B6"},
    "lugia":    {"display": "Lugia",    "price": "$2.00", "color": "#5DADE2"},
    "ho-oh":    {"display": "Ho-Oh",    "price": "$2.00", "color": "#E67E22"},
    "zapdos":   {"display": "Zapdos",   "price": "$2.00", "color": "#F1C40F"},
    "moltres":  {"display": "Moltres",  "price": "$2.00", "color": "#E74C3C"},
    "articuno": {"display": "Articuno", "price": "$2.00", "color": "#85C1E9"},
    "deoxys":   {"display": "Deoxys",   "price": "$2.00", "color": "#27AE60"},
}

# Hunt included free so users can see the app is working before buying.
FREE_HUNTS: List[str] = []

PROJECT_ROOT   = Path(__file__).resolve().parent.parent.parent
LICENSE_FILE   = PROJECT_ROOT / "data" / "licenses.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _b32encode(data: bytes) -> str:
    return base64.b32encode(data).decode().rstrip("=")


def _b32decode(s: str) -> bytes:
    # Pad to multiple of 8
    padding = (8 - len(s) % 8) % 8
    return base64.b32decode(s + "=" * padding)


def _sign(payload_b32: str) -> str:
    """Return 8-char base32 HMAC tag over the payload string."""
    mac = hmac.new(MASTER_SECRET, payload_b32.encode(), hashlib.sha256).digest()
    return _b32encode(mac)[:8]


def _payload_to_b32(hunts: List[str], email: str, issued: str) -> str:
    blob = json.dumps({"hunts": hunts, "email": email, "issued": issued},
                      separators=(",", ":"), sort_keys=True)
    return _b32encode(blob.encode())


def _parse_payload(payload_b32: str) -> Optional[dict]:
    try:
        raw = _b32decode(payload_b32)
        return json.loads(raw.decode())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_key(hunts: List[str], email: str, issued: str) -> str:
    """
    Generate a signed license key for the given list of hunt IDs.

    Args:
        hunts:  list of hunt IDs, e.g. ["mewtwo", "lugia"]
        email:  buyer email (embedded in key for traceability)
        issued: ISO date string e.g. "2026-04-08"

    Returns:
        A human-readable key string, e.g.:
            MEWTWO-BJLABCDE1234XXXX-ZXQRWVUT
    """
    hunts_clean = sorted({h.lower() for h in hunts})
    prefix      = "-".join(h.upper() for h in hunts_clean)
    payload     = _payload_to_b32(hunts_clean, email, issued)
    tag         = _sign(payload)
    return f"{prefix}-{payload}-{tag}"


def validate_key(key: str) -> Optional[List[str]]:
    """
    Validate a license key.

    Returns:
        List of unlocked hunt IDs if valid, or None if invalid/tampered.
    """
    key = key.strip().upper()
    # Key must end with -<8 chars>
    m = re.match(r"^(.+)-([A-Z2-7]{8})$", key)
    if not m:
        return None

    body, tag = m.group(1), m.group(2)

    # Body is <PREFIX(es)>-<PAYLOAD_B32>; we need the last segment as payload
    parts = body.split("-")
    if len(parts) < 2:
        return None

    # The payload is everything after the last "-" in the hunt prefix block.
    # Since hunt names never contain digits, payload is the first segment that
    # looks like base32 data (contains digits or is long).
    # Strategy: try splitting from the right — last token before tag is payload.
    payload_b32 = parts[-1]
    expected_tag = _sign(payload_b32)

    if not hmac.compare_digest(tag, expected_tag):
        return None

    data = _parse_payload(payload_b32)
    if data is None or "hunts" not in data:
        return None

    return [h.lower() for h in data["hunts"]]


# ---------------------------------------------------------------------------
# Persistent local license store
# ---------------------------------------------------------------------------

def _load_store() -> List[str]:
    if LICENSE_FILE.exists():
        try:
            return json.loads(LICENSE_FILE.read_text())
        except Exception:
            pass
    return []


def _save_store(keys: List[str]) -> None:
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(keys, indent=2))


def activate_key(key: str) -> tuple[bool, str, List[str]]:
    """
    Attempt to activate a license key.

    Returns:
        (success: bool, message: str, unlocked_hunts: List[str])
    """
    hunts = validate_key(key)
    if hunts is None:
        return False, "Invalid or tampered license key.", []

    store = _load_store()
    key_clean = key.strip().upper()
    if key_clean not in store:
        store.append(key_clean)
        _save_store(store)

    return True, f"Activated! Unlocked: {', '.join(h.title() for h in hunts)}", hunts


def get_unlocked_hunts() -> List[str]:
    """
    Return the full list of hunt IDs unlocked by all stored keys.
    Always includes FREE_HUNTS.
    """
    unlocked = set(FREE_HUNTS)
    for key in _load_store():
        hunts = validate_key(key)
        if hunts:
            unlocked.update(hunts)
    return sorted(unlocked)


def is_hunt_unlocked(hunt_id: str) -> bool:
    return hunt_id.lower() in get_unlocked_hunts()
