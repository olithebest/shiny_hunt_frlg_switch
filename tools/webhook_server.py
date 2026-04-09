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
BREVO_API_KEY  = os.environ.get("BREVO_API_KEY", "")    # from brevo.com — free, 300 emails/day
FROM_EMAIL     = os.environ.get("FROM_EMAIL", "")        # your verified sender email in Brevo
WEBHOOK_SECRET = os.environ.get("ITCH_WEBHOOK_SECRET", "")

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
    """Send the license key via Brevo HTTPS API (no SMTP — works on Render free tier)."""
    if not BREVO_API_KEY or not FROM_EMAIL:
        return False, "BREVO_API_KEY or FROM_EMAIL not set"

    pokemon = HUNT_CATALOGUE.get(hunt_id, {}).get("display", hunt_id)
    body    = EMAIL_TEMPLATE.format(product_title=product_title, key=key, pokemon=pokemon)

    payload = json.dumps({
        "sender":      {"name": "Shiny Hunter", "email": FROM_EMAIL},
        "to":          [{"email": to_email}],
        "subject":     f"Your license key for {product_title}",
        "textContent": body,
    }).encode()

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key":      BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        log.info(f"Key emailed via Brevo to {to_email} for {hunt_id}: {result}")
        return True, None
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode(errors="replace")
        log.error(f"Brevo API error {exc.code}: {body_err}")
        return False, f"Brevo {exc.code}: {body_err}"
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
            return f"<h2>Email FAILED</h2><p>{err}</p><p>BREVO_API_KEY set: {bool(BREVO_API_KEY)} | FROM: {FROM_EMAIL}</p>", 500
    except Exception:
        tb = traceback.format_exc()
        log.error(f"test_email crashed:\n{tb}")
        return f"<h2>Crash</h2><pre>{tb}</pre>", 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "email_configured": bool(BREVO_API_KEY and FROM_EMAIL)}), 200


if __name__ == "__main__":
    if not BREVO_API_KEY:
        log.warning("BREVO_API_KEY not set — edit .env before going live")
    if not FROM_EMAIL:
        log.warning("FROM_EMAIL not set — edit .env before going live")

    port = int(os.environ.get("PORT", 5051))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    log.info(f"Webhook server starting on http://{host}:{port}")
    log.info(f"Test email at: http://localhost:{port}/test-email?to=your@email.com&hunt=mewtwo")
    app.run(host=host, port=port, debug=False)
