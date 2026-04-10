#!/usr/bin/env python3
"""
webhook_server.py — Automatic license key delivery for Shiny Hunter FRLG
=========================================================================
Receives purchase webhooks from itch.io, generates a license key,
and emails it to the buyer automatically.

SETUP
-----
1. Copy .env.example to .env and fill in your credentials
2. Install dependencies: pip install flask python-dotenv
3. Start the server: python tools/webhook_server.py
4. Expose it publicly for testing: ngrok http 5051
5. Paste the ngrok URL into itch.io → Edit page → Webhooks

itch.io webhook URL to enter:  https://YOUR-NGROK-URL/webhook/itch

ITCH.IO PRODUCT TITLE → HUNT MAPPING
--------------------------------------
The server maps your itch.io product titles to hunt IDs.
Edit TITLE_TO_HUNT below to match your exact itch.io page titles.
"""

import os
import sys
import json
import logging
import urllib.request
import urllib.error
import base64
from datetime import date
from pathlib import Path

from flask import Flask, request, jsonify

# Load .env file if present (pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # dotenv not installed, rely on real env vars

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.licensing.license_manager import generate_key, HUNT_CATALOGUE

# ---------------------------------------------------------------------------
# Config — all sensitive values come from environment variables / .env file
# ---------------------------------------------------------------------------
MAILJET_API_KEY    = os.environ.get("MAILJET_API_KEY", "")     # from mailjet.com — free 200/day
MAILJET_SECRET_KEY = os.environ.get("MAILJET_SECRET_KEY", "")  # from mailjet.com
FROM_EMAIL         = os.environ.get("FROM_EMAIL", "")           # your verified sender email
WEBHOOK_SECRET    = os.environ.get("ITCH_WEBHOOK_SECRET", "")
ITCH_API_KEY       = os.environ.get("ITCH_API_KEY", "")         # itch.io API key for purchase polling

# ---------------------------------------------------------------------------
# Map your exact itch.io product TITLES to hunt IDs.
# Go to your itch.io dashboard and copy the exact title of each product page.
# ---------------------------------------------------------------------------
TITLE_TO_HUNT = {
    "Shiny Hunter FRLG — Mewtwo Hunt":   "mewtwo",
    "Shiny Hunter FRLG — Lugia Hunt":    "lugia",
    "Shiny Hunter FRLG — Ho-Oh Hunt":    "ho-oh",
    "Shiny Hunter FRLG — Zapdos Hunt":   "zapdos",
    "Shiny Hunter FRLG — Moltres Hunt":  "moltres",
    "Shiny Hunter FRLG — Articuno Hunt": "articuno",
    "Shiny Hunter FRLG — Deoxys Hunt":   "deoxys",
}

# ---------------------------------------------------------------------------
# Map itch.io numeric game IDs to hunt IDs.
# Run:  python tools/webhook_server.py --list-games  to see your game IDs.
# ---------------------------------------------------------------------------
GAME_ID_TO_HUNT = {
    4462783: "mewtwo",   # Shiny Hunter FRLG — Mewtwo Hunt
    # Add more as you publish new hunt pages:
    # 9999999: "lugia",
}

# ---------------------------------------------------------------------------
# Processed purchase tracking — persisted to data/processed_purchases.json
# so we don't re-send emails after a server restart.
# ---------------------------------------------------------------------------
_PROCESSED_FILE = Path(__file__).resolve().parent.parent / "data" / "processed_purchases.json"
_processed_ids: set = set()


def _load_processed_ids():
    global _processed_ids
    try:
        if _PROCESSED_FILE.exists():
            _processed_ids = set(json.loads(_PROCESSED_FILE.read_text()))
            log.info(f"Loaded {len(_processed_ids)} already-processed purchase IDs")
    except Exception as exc:
        log.warning(f"Could not load processed_purchases.json: {exc}")


def _save_processed_ids():
    try:
        _PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PROCESSED_FILE.write_text(json.dumps(sorted(_processed_ids)))
    except Exception as exc:
        log.warning(f"Could not save processed_purchases.json: {exc}")


def poll_itch_purchases() -> list:
    """Fetch purchases from the itch.io API and email keys for any new ones."""
    if not ITCH_API_KEY:
        log.warning("ITCH_API_KEY not set — skipping poll")
        return [{"error": "ITCH_API_KEY not set"}]

    results = []
    for game_id, hunt_id in GAME_ID_TO_HUNT.items():
        try:
            url = f"https://itch.io/api/1/{ITCH_API_KEY}/game/{game_id}/purchases"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            purchases = data.get("purchases", [])
            log.info(f"Poll: game {game_id} ({hunt_id}): {len(purchases)} total purchases")

            for purchase in purchases:
                pid = str(purchase.get("id", ""))
                if not pid or pid in _processed_ids:
                    continue  # already handled

                email = purchase.get("email", "")
                if not email or "@" not in email:
                    log.warning(f"Purchase {pid} has no valid email — marking processed")
                    _processed_ids.add(pid)
                    continue

                display   = HUNT_CATALOGUE.get(hunt_id, {}).get("display", hunt_id)
                title     = f"Shiny Hunter FRLG \u2014 {display} Hunt"
                key       = generate_key(hunts=[hunt_id], email=email, issued=date.today().isoformat())
                sent, err = send_key_email(email, title, hunt_id, key)

                _processed_ids.add(pid)
                _save_processed_ids()

                log.info(f"Poll processed purchase {pid}: {email}/{hunt_id} sent={sent} err={err}")
                results.append({"pid": pid, "email": email, "hunt": hunt_id, "sent": sent, "err": err})

        except Exception as exc:
            log.error(f"Error polling game {game_id}: {exc}")
            results.append({"game_id": game_id, "error": str(exc)})

    return results


# ---------------------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------

EMAIL_TEMPLATE = """\
Hi there!

Thank you for purchasing {product_title}!

Here is your license key:

    {key}

HOW TO ACTIVATE
---------------
1. Unzip the downloaded shiny-hunter package and run setup.bat
2. Open a terminal in the shiny-hunter folder and run:
       python tools/store_server.py
3. A browser page will open at http://localhost:5050
4. Paste the key above into the activation box and click Activate
5. Your {pokemon} hunt is now unlocked — run start.bat to begin!

If you have any issues, reply to this email.

Happy hunting!
"""


def send_key_email(to_email: str, product_title: str, hunt_id: str, key: str):
    """Send the license key via Mailjet HTTPS API (works on Render free tier)."""
    if not MAILJET_API_KEY or not MAILJET_SECRET_KEY or not FROM_EMAIL:
        return False, "MAILJET_API_KEY, MAILJET_SECRET_KEY or FROM_EMAIL not set"

    pokemon = HUNT_CATALOGUE.get(hunt_id, {}).get("display", hunt_id)
    body    = EMAIL_TEMPLATE.format(product_title=product_title, key=key, pokemon=pokemon)

    payload = json.dumps({
        "Messages": [{
            "From": {"Email": FROM_EMAIL, "Name": "Shiny Hunter"},
            "To":   [{"Email": to_email}],
            "Subject":  f"Your license key for {product_title}",
            "TextPart": body,
        }]
    }).encode()

    credentials = base64.b64encode(f"{MAILJET_API_KEY}:{MAILJET_SECRET_KEY}".encode()).decode()
    req = urllib.request.Request(
        "https://api.mailjet.com/v3.1/send",
        data=payload,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        log.info(f"Key emailed via Mailjet to {to_email} for {hunt_id}: {result}")
        return True, None
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode(errors="replace")
        log.error(f"Mailjet API error {exc.code}: {body_err}")
        return False, f"Mailjet {exc.code}: {body_err}"
    except Exception as exc:
        log.error(f"Failed to send email to {to_email}: {exc}")
        return False, str(exc)


@app.route("/webhook/itch", methods=["POST"])
def itch_webhook():
    """
    itch.io calls this URL when a purchase is made.
    Expected JSON payload (itch.io purchase webhook format):
    {
        "purchase": {
            "email": "buyer@example.com",
            "price": 200,
            ...
        },
        "game": {
            "title": "Shiny Hunter FRLG — Mewtwo Hunt",
            ...
        }
    }
    """
    data = request.get_json(silent=True)
    if not data:
        log.warning("Webhook received non-JSON or empty body")
        return jsonify({"error": "invalid payload"}), 400

    log.info(f"Webhook received: {json.dumps(data, indent=2)}")

    # Extract buyer email and product title from itch.io payload
    try:
        buyer_email   = data["purchase"]["email"]
        product_title = data["game"]["title"]
    except (KeyError, TypeError):
        log.warning(f"Missing expected fields in webhook payload: {data}")
        return jsonify({"error": "missing fields"}), 400

    # Resolve hunt ID from product title
    hunt_id = TITLE_TO_HUNT.get(product_title)
    if not hunt_id:
        log.warning(f"Unknown product title: '{product_title}' — check TITLE_TO_HUNT mapping")
        return jsonify({"error": f"unknown product: {product_title}"}), 400

    # Generate the license key
    key = generate_key(
        hunts=[hunt_id],
        email=buyer_email,
        issued=date.today().isoformat(),
    )

    log.info(f"Generated key for {buyer_email} / {hunt_id}: {key}")

    # Send the email
    sent, err = send_key_email(buyer_email, product_title, hunt_id, key)

    if sent:
        return jsonify({"ok": True, "hunt": hunt_id, "email": buyer_email}), 200
    else:
        # Key was generated but email failed — log it so you can send manually
        log.error(f"EMAIL FAILED — Manual key for {buyer_email}: {key} — Error: {err}")
        return jsonify({"ok": False, "error": "email failed", "key": key}), 500


@app.route("/test-email", methods=["GET"])
def test_email():
    """
    Quick test endpoint — hit this in your browser to verify email works.
    Usage: http://localhost:5051/test-email?to=your@email.com&hunt=mewtwo
    """
    import traceback
    try:
        to    = request.args.get("to", FROM_EMAIL)
        hunt  = request.args.get("hunt", "mewtwo")
        title = f"Shiny Hunter FRLG — {HUNT_CATALOGUE.get(hunt, {}).get('display', hunt)} Hunt"

        key       = generate_key(hunts=[hunt], email=to, issued=date.today().isoformat())
        sent, err = send_key_email(to, title, hunt, key)

        if sent:
            return f"<h2>Test email sent to {to}</h2><p>Key: <code>{key}</code></p>", 200
        else:
            return f"<h2>Email FAILED</h2><p>{err}</p><p>MAILJET keys set: {bool(MAILJET_API_KEY and MAILJET_SECRET_KEY)} | FROM: {FROM_EMAIL}</p>", 500
    except Exception:
        tb = traceback.format_exc()
        log.error(f"test_email crashed:\n{tb}")
        return f"<h2>Crash</h2><pre>{tb}</pre>", 500


@app.route("/poll", methods=["GET", "POST"])
def poll():
    """
    Called by a cron job every 5 minutes to check for new itch.io purchases.
    Set up free at cron-job.org:
      URL:      https://shiny-hunt-frlg-switch.onrender.com/poll
      Interval: Every 5 minutes
    """
    results = poll_itch_purchases()
    new_count = sum(1 for r in results if "pid" in r)
    return jsonify({"ok": True, "new_purchases_processed": new_count, "details": results}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "email_configured": bool(MAILJET_API_KEY and MAILJET_SECRET_KEY and FROM_EMAIL),
        "poll_configured":  bool(ITCH_API_KEY and GAME_ID_TO_HUNT),
    }), 200


# Load already-processed purchase IDs on startup so we never double-send
_load_processed_ids()


if __name__ == "__main__":
    if not MAILJET_API_KEY or not MAILJET_SECRET_KEY:
        log.warning("MAILJET_API_KEY / MAILJET_SECRET_KEY not set — edit .env before going live")
    if not FROM_EMAIL:
        log.warning("FROM_EMAIL not set — edit .env before going live")

    port = int(os.environ.get("PORT", 5051))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    log.info(f"Webhook server starting on http://{host}:{port}")
    log.info(f"Test email at: http://localhost:{port}/test-email?to=your@email.com&hunt=mewtwo")
    app.run(host=host, port=port, debug=False)
