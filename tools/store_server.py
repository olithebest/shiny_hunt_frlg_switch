#!/usr/bin/env python3
"""
store_server.py — Local store server for Shiny Hunter FRLG
============================================================
Serves the HTML store page and handles license key activation.

Usage:
    python tools/store_server.py

Then open http://localhost:5050 in your browser.
The server only listens on localhost — it is not accessible from the internet.
"""

import sys
import os
import webbrowser
import threading
import urllib.request
import json as _json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load .env so SHINY_HUNTER_SECRET is available on the developer's machine
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

from flask import Flask, send_file, request, jsonify
from src.licensing.license_manager import activate_key, store_server_validated, get_unlocked_hunts

HTML_FILE      = os.path.join(os.path.dirname(__file__), "..", "src", "gui", "store.html")
PORT           = 5050
RENDER_URL     = "https://shiny-hunt-frlg-switch.onrender.com"
_DEFAULT_SEC   = "change-me-before-shipping-use-a-long-random-string-here"
_HAS_LOCAL_KEY = os.environ.get("SHINY_HUNTER_SECRET", _DEFAULT_SEC) != _DEFAULT_SEC

app = Flask(__name__)


@app.route("/")
def index():
    return send_file(os.path.abspath(HTML_FILE))


@app.route("/api/status")
def status():
    return jsonify({"unlocked": get_unlocked_hunts()})


@app.route("/api/activate", methods=["POST"])
def activate():
    key = (request.json or {}).get("key", "").strip()
    if not key:
        return jsonify({"ok": False, "message": "No key provided."}), 400

    if _HAS_LOCAL_KEY:
        # Developer machine: validate locally (fast, works offline)
        ok, message, hunts = activate_key(key)
        return jsonify({"ok": ok, "message": message, "hunts": hunts})

    # Buyer machine: validate via Render server (secret lives there only)
    try:
        payload = _json.dumps({"key": key}).encode()
        req = urllib.request.Request(
            f"{RENDER_URL}/validate-key",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = _json.loads(resp.read())
    except Exception as e:
        return jsonify({"ok": False, "message": f"Could not reach activation server (the server may be waking up — wait 30 seconds and try again).\n({e})"}), 200

    if not result.get("ok"):
        return jsonify({"ok": False, "message": result.get("error", "Invalid or tampered license key.")}), 200

    hunts = result["hunts"]
    store_server_validated(hunts)
    return jsonify({"ok": True, "message": f"Activated! Unlocked: {', '.join(h.title() for h in hunts)}", "hunts": hunts})


def _open_browser():
    import time
    time.sleep(0.8)  # wait for Flask to be ready
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    print(f"\n✨  Shiny Hunter FRLG — Store")
    print(f"    Opening http://localhost:{PORT} ...\n")
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)
