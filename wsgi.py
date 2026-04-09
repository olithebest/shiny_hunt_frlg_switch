"""
wsgi.py — Gunicorn entry point for Render deployment
=====================================================
Render (and gunicorn) import this file to get the Flask app.
Do not rename or move this file.
"""
import sys
from pathlib import Path

# Ensure project root is on the path so src.licensing imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.webhook_server import app  # noqa: F401 — gunicorn needs this name
