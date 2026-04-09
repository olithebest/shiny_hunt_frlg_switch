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
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "")   # your Gmail address
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")  # Gmail App Password (spaces stripped)
WEBHOOK_SECRET = os.environ.get("ITCH_WEBHOOK_SECRET", "")  # optional: itch.io webhook secret for verification

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


def send_key_email(to_email: str, product_title: str, hunt_id: str, key: str) -> bool:
    """Send the license key to the buyer via Gmail SMTP."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASS:
        log.error("GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — cannot send email")
        return False

    pokemon = HUNT_CATALOGUE.get(hunt_id, {}).get("display", hunt_id)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your license key for {product_title}"
    msg["From"]    = f"Shiny Hunter <{GMAIL_ADDRESS}>"
    msg["To"]      = to_email

    body = EMAIL_TEMPLATE.format(
        product_title=product_title,
        key=key,
        pokemon=pokemon,
    )
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
        log.info(f"Key emailed to {to_email} for {hunt_id}")
        return True, None
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
    to    = request.args.get("to", GMAIL_ADDRESS)
    hunt  = request.args.get("hunt", "mewtwo")
    title = f"Shiny Hunter FRLG — {HUNT_CATALOGUE.get(hunt, {}).get('display', hunt)} Hunt"

    key  = generate_key(hunts=[hunt], email=to, issued=date.today().isoformat())
    sent, err = send_key_email(to, title, hunt, key)

    if sent:
        return f"<h2>Test email sent to {to}</h2><p>Key: <code>{key}</code></p>", 200
    else:
        return f"<h2>Email FAILED</h2><p>{err}</p><p>GMAIL_ADDRESS set: {bool(GMAIL_ADDRESS)} | APP_PASS set: {bool(GMAIL_APP_PASS)} | Length: {len(GMAIL_APP_PASS)}</p>", 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "email_configured": bool(GMAIL_ADDRESS and GMAIL_APP_PASS)}), 200


if __name__ == "__main__":
    if not GMAIL_ADDRESS:
        log.warning("GMAIL_ADDRESS not set — edit .env before going live")
    if not GMAIL_APP_PASS:
        log.warning("GMAIL_APP_PASSWORD not set — edit .env before going live")

    port = int(os.environ.get("PORT", 5051))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    log.info(f"Webhook server starting on http://{host}:{port}")
    log.info(f"Test email at: http://localhost:{port}/test-email?to=your@email.com&hunt=mewtwo")
    app.run(host=host, port=port, debug=False)
