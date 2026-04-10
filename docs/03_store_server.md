# `tools/store_server.py` — Documentation

## Purpose

Local Flask server that serves the buyer's license key activation page.
Runs on the buyer's machine at `http://localhost:5050`.
Never exposed to the internet — it only listens on `127.0.0.1`.

---

## How Activation Works

Two paths depending on whether the machine has the HMAC secret:

```
store_server.py starts
    ↓
load_dotenv(.env)     ← loads SHINY_HUNTER_SECRET if present
    ↓
_HAS_LOCAL_KEY check
    ├── True  (developer machine or someone with .env)
    │     → validate_key() locally using HMAC — fast, offline
    │     → activate_key() saves key to data/licenses.json
    │
    └── False (buyer machine — no .env)
          → POST to Render /validate-key
          → Render checks HMAC with real secret
          → if valid: store_server_validated(hunts) saves to data/unlocked.json
```

---

## Constants

### `PORT = 5050`
The local port `store_server.py` listens on. Open `http://localhost:5050` in a browser.

### `RENDER_URL`
```python
RENDER_URL = "https://shiny-hunt-frlg-switch.onrender.com"
```
Base URL of the deployed Render server. Used for remote key validation.

### `_DEFAULT_SEC`
The placeholder secret string baked into `license_manager.py`.
Used to detect whether a real secret is loaded.

### `_HAS_LOCAL_KEY`
```python
_HAS_LOCAL_KEY = os.environ.get("SHINY_HUNTER_SECRET", _DEFAULT_SEC) != _DEFAULT_SEC
```
`True` if a real (non-placeholder) secret is available in the environment.
Set at startup, after `load_dotenv()` runs.

> ⚠️ **Common bug**: If `store_server.py` is already running in the background
> from a previous session (without `load_dotenv`), the new process will fail to
> bind port 5050 silently and the old broken process keeps serving requests.
> **Fix**: Check for and kill any process on port 5050 before restarting.
> ```powershell
> netstat -ano | findstr ":5050"
> Stop-Process -Id <PID> -Force
> ```

---

## Startup Sequence

1. `load_dotenv()` — loads `.env` from project root (developer only)
2. Import `license_manager` — `MASTER_SECRET` is set from env at import time
3. Compute `_HAS_LOCAL_KEY` — determines local vs remote validation path
4. Flask app starts on `127.0.0.1:5050`
5. Browser opens automatically after 0.8 seconds

---

## HTTP Endpoints

### `GET /`
Serves `src/gui/store.html` — the activation page UI.

---

### `GET /api/status`
Returns which hunts are currently unlocked on this machine.

**Response:**
```json
{"unlocked": ["mewtwo"]}
```
Empty array means no hunts are active yet.

---

### `POST /api/activate`
**The main endpoint** — validates a license key and unlocks the hunt.

**Request body:** `{"key": "MEWTWO-..."}`

**Local path** (`_HAS_LOCAL_KEY == True`):
```
activate_key(key)
  → validate_key(key)       # HMAC check with local secret
  → save to data/licenses.json
  → return {"ok": true, "message": "Activated! Unlocked: Mewtwo", "hunts": ["mewtwo"]}
```

**Remote path** (`_HAS_LOCAL_KEY == False`):
```
POST https://shiny-hunt-frlg-switch.onrender.com/validate-key {"key": "..."}
  → Render checks HMAC
  → if valid: store_server_validated(hunts)  # saves to data/unlocked.json
  → return {"ok": true, "message": "Activated! Unlocked: Mewtwo", "hunts": ["mewtwo"]}
```

**Error responses:**
- No key provided: `{"ok": false, "message": "No key provided."}`
- Invalid key: `{"ok": false, "message": "Invalid or tampered license key."}`
- Network error: `{"ok": false, "message": "Could not reach activation server..."}`

---

## Running It

```bash
python tools/store_server.py
```

Browser opens automatically at `http://localhost:5050`.
To stop it: **Ctrl+C** in the terminal.

---

## Files Written

| File | Written when | Contains |
|------|-------------|---------|
| `data/licenses.json` | Local validation succeeds | Raw key strings (developer machine) |
| `data/unlocked.json` | Remote validation succeeds | Hunt ID strings (buyer machine) |
