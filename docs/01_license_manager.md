# `src/licensing/license_manager.py` — Documentation

## Purpose

Generates and validates cryptographically signed license keys, and manages
which hunts are unlocked on the local machine.

---

## Key Format

```
MEWTWO-<BASE32_PAYLOAD>-<8_CHAR_HMAC_TAG>
```

Example:
```
MEWTWO-BJLABCDE1234XXXX-ZXQRWVUT
```

- **Prefix** — one or more hunt names in UPPER_CASE separated by `-`.
  Multi-hunt keys look like `MEWTWO-LUGIA-<payload>-<tag>`.
- **Payload** — Base32-encoded JSON blob containing:
  ```json
  {"hunts": ["mewtwo"], "email": "buyer@example.com", "issued": "2026-04-09"}
  ```
- **Tag** — first 8 characters of HMAC-SHA256 over the raw payload bytes,
  using the master secret. Verifies the key has not been tampered with.

---

## Security Properties

| Property | How it works |
|----------|-------------|
| Unforgeable | Without `SHINY_HUNTER_SECRET`, the 8-char HMAC tag cannot be computed |
| Self-contained | Works fully offline once validated and saved to disk |
| Traceable | Buyer email embedded in payload for audit trail |
| No plaintext secret on buyer machine | Buyers call Render `/validate-key`; secret never leaves the server |

---

## Constants

### `MASTER_SECRET`
```python
MASTER_SECRET = os.environ.get("SHINY_HUNTER_SECRET", _DEFAULT_SECRET).encode()
```
Read from the `SHINY_HUNTER_SECRET` environment variable (set in `.env` on
developer machine; set in Render environment on the cloud server).

> ⚠️ **Critical**: This value must be identical on the machine that generates
> keys (webhook_server.py on Render) and the machine that validates them locally.
> Buyers never need this — they validate via the Render `/validate-key` endpoint.

### `HUNT_CATALOGUE`
```python
HUNT_CATALOGUE = {
    "mewtwo": {"display": "Mewtwo", "price": "$2.00", "color": "#9B59B6"},
    ...
}
```
Maps internal hunt IDs (lowercase strings) to display metadata used in emails
and the GUI. Add a new entry here when adding a new hunt.

### `FREE_HUNTS`
List of hunt IDs that are always unlocked, no key required. Empty by default.

### `LICENSE_FILE`
`data/licenses.json` — stores activated key strings for developer/local use.

### `UNLOCKED_FILE`
`data/unlocked.json` — stores hunt IDs unlocked by Render-validated keys
(buyers who don't have the local secret).

---

## Internal Helper Functions

### `_b32encode(data: bytes) -> str`
Encodes bytes to Base32 string, stripping trailing `=` padding.

### `_b32decode(s: str) -> bytes`
Decodes a Base32 string back to bytes, re-adding padding as needed.

### `_sign(payload_b32: str) -> str`
Computes HMAC-SHA256 over `payload_b32` using `MASTER_SECRET`, returns the
first 8 characters of the Base32-encoded digest. This is the key's integrity tag.

### `_payload_to_b32(hunts, email, issued) -> str`
Serializes the key payload to a canonical JSON string (sorted keys, no spaces)
and Base32-encodes it.

### `_parse_payload(payload_b32: str) -> dict | None`
Decodes and JSON-parses a payload. Returns `None` on any error.

---

## Public API

### `generate_key(hunts, email, issued) -> str`
Generates a signed license key for a list of hunt IDs.

**Parameters:**
- `hunts` — list of hunt IDs, e.g. `["mewtwo"]`
- `email` — buyer's email address (embedded for traceability)
- `issued` — ISO date string, e.g. `"2026-04-09"`

**Returns:** Key string like `MEWTWO-<payload>-<tag>`

**Example:**
```python
key = generate_key(hunts=["mewtwo"], email="buyer@example.com", issued="2026-04-09")
```

---

### `validate_key(key: str) -> list[str] | None`
Validates a license key's HMAC signature.

**Returns:**
- List of unlocked hunt IDs if valid (e.g. `["mewtwo"]`)
- `None` if the key is malformed or the HMAC doesn't match

**How it works:**
1. Strips and uppercases the key
2. Regex splits off the last 8-char tag
3. Searches for the Base32 payload segment (last `-` separated token before tag)
4. Recomputes the expected HMAC tag
5. Uses `hmac.compare_digest()` for timing-safe comparison
6. Parses payload JSON and returns the `hunts` list

---

### `activate_key(key: str) -> (bool, str, list[str])`
Validates a key and saves it to `data/licenses.json` if valid.

**Returns:** `(success, message, unlocked_hunts)`

Used on developer machines (where `SHINY_HUNTER_SECRET` is available in `.env`).

---

### `store_server_validated(hunts: list[str]) -> None`
Persists hunt IDs that were validated by the Render server (remote validation).
Merges with any existing entries in `data/unlocked.json`.

Used by `store_server.py` on buyer machines that don't have the local secret.

---

### `get_unlocked_hunts() -> list[str]`
Returns the complete list of unlocked hunt IDs from all sources:
1. `FREE_HUNTS` (always included)
2. Keys in `data/licenses.json` (validated with local secret)
3. `data/unlocked.json` (validated via Render)

---

### `is_hunt_unlocked(hunt_id: str) -> bool`
Returns `True` if the given hunt ID appears in `get_unlocked_hunts()`.
Used by `gui/app.py` to gate the Start button.
