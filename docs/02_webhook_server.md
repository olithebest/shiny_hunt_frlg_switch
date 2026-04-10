# `tools/webhook_server.py` — Documentation

## Purpose

Flask server deployed on **Render.com** that handles the full purchase-to-key
pipeline:

1. Polls the itch.io API every 5 minutes (triggered by cron-job.org)
2. For each new purchase: generates a license key and emails it to the buyer
3. Validates keys for buyers whose local machine doesn't have the HMAC secret
4. Provides health check and test endpoints for diagnostics

---

## Deployment

| Component | Value |
|-----------|-------|
| Hosting | Render.com (free tier, Docker) |
| Public URL | `https://shiny-hunt-frlg-switch.onrender.com` |
| Port | `10000` (set by Render via `$PORT`) |
| Start command | `gunicorn wsgi:app --bind 0.0.0.0:${PORT:-10000}` |

---

## Environment Variables

All secrets come from environment variables — never hardcoded.

| Variable | Where to get it | Purpose |
|----------|----------------|---------|
| `MAILJET_API_KEY` | mailjet.com | Email API auth |
| `MAILJET_SECRET_KEY` | mailjet.com | Email API auth |
| `FROM_EMAIL` | Your verified Mailjet sender | Reply-to / From address |
| `SHINY_HUNTER_SECRET` | You set it | HMAC signing secret for license keys |
| `ITCH_API_KEY` | itch.io account settings | Polls purchase list |

---

## Configuration Constants

### `TITLE_TO_HUNT`
```python
TITLE_TO_HUNT = {
    "Shiny Hunter FRLG — Mewtwo Hunt": "mewtwo",
    ...
}
```
Maps your exact itch.io product page titles to internal hunt IDs.
Must match the title exactly (including em dash `—`).

### `GAME_ID_TO_HUNT`
```python
GAME_ID_TO_HUNT = {
    4462783: "mewtwo",
}
```
Maps itch.io numeric game IDs to hunt IDs.
Used by the polling system. Get your game IDs by calling:
`https://itch.io/api/1/{ITCH_API_KEY}/my-games`

---

## Purchase Deduplication

### `_PROCESSED_FILE`
Path: `data/processed_purchases.json`

Stores a list of itch.io purchase IDs that have already been processed.
Checked before sending every email — prevents duplicate keys on server restart.

### `_load_processed_ids()`
Called once at startup. Loads the set of already-processed IDs from disk into
the in-memory `_processed_ids` set.

### `_save_processed_ids()`
Called after every new purchase is processed. Writes `_processed_ids` back to
disk as a sorted JSON array.

---

## Core Functions

### `poll_itch_purchases() -> list`
Main polling logic. Called by the `/poll` endpoint every 5 minutes.

**Flow for each game in `GAME_ID_TO_HUNT`:**
1. Calls `https://itch.io/api/1/{ITCH_API_KEY}/game/{game_id}/purchases`
2. Iterates each purchase in the response
3. Skips purchases whose ID is already in `_processed_ids`
4. Validates the buyer's email
5. Calls `generate_key()` to create a signed license key
6. Calls `send_key_email()` to deliver the key
7. Adds the purchase ID to `_processed_ids` and saves to disk

**Returns:** List of result dicts, one per processed purchase.

---

### `send_key_email(to_email, product_title, hunt_id, key) -> (bool, str|None)`
Sends the license key to the buyer via **Mailjet HTTPS API**.

> ℹ️ Mailjet is used (not SMTP) because Render's free tier blocks outgoing
> TCP ports 465 and 587. Mailjet's REST API over HTTPS port 443 is unaffected.

**Parameters:**
- `to_email` — buyer's email address
- `product_title` — full product name (used in email subject)
- `hunt_id` — e.g. `"mewtwo"` (used to look up Pokémon display name)
- `key` — the signed license key string

**Returns:** `(True, None)` on success, `(False, error_message)` on failure.

**Email body:** Filled from `EMAIL_TEMPLATE` — includes the key, activation
instructions, and a reference to `store_server.py`.

---

## HTTP Endpoints

### `POST /webhook/itch`
Receives purchase webhook payloads from itch.io (if itch.io's webhook feature
becomes available). Expected payload:
```json
{
  "purchase": {"email": "buyer@example.com"},
  "game": {"title": "Shiny Hunter FRLG — Mewtwo Hunt"}
}
```
Generates a key and emails it immediately.

> Currently not used — itch.io's UI doesn't expose webhooks. `/poll` is used instead.

---

### `GET/POST /poll`
Called by **cron-job.org** every 5 minutes. Triggers `poll_itch_purchases()`.

**Response:**
```json
{
  "ok": true,
  "new_purchases_processed": 1,
  "details": [{"pid": "123", "email": "...", "hunt": "mewtwo", "sent": true}]
}
```

Setup: cron-job.org → URL: `https://shiny-hunt-frlg-switch.onrender.com/poll` → every 5 min.

---

### `POST /validate-key`
Called by `store_server.py` on buyer machines to validate a key remotely
(buyers don't have `SHINY_HUNTER_SECRET`).

**Request body:** `{"key": "MEWTWO-..."}`

**Response (valid):** `{"ok": true, "hunts": ["mewtwo"]}`
**Response (invalid):** `{"ok": false, "error": "Invalid or tampered license key."}`

---

### `GET /test-email`
Developer utility — sends a real test email with a generated key.

**Usage:** `https://shiny-hunt-frlg-switch.onrender.com/test-email?to=you@gmail.com&hunt=mewtwo`

**Response:** HTML page showing the sent key, or the error message if email failed.

---

### `GET /health`
Returns server status. Used by monitoring and keep-alive pings.

**Response:**
```json
{
  "status": "ok",
  "email_configured": true,
  "poll_configured": true
}
```
`poll_configured` is `true` when both `ITCH_API_KEY` and `GAME_ID_TO_HUNT` are set.
