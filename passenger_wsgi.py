"""
passenger_wsgi.py — cPanel Phusion Passenger entry point
=========================================================
Wraps the FastAPI (ASGI) application as a WSGI app for cPanel.

cPanel Setup Python App configuration:
  Application startup file:  passenger_wsgi.py
  Application Entry point:   application
  Python version:            3.11+
  Virtualenv path:           (auto-created by cPanel)

After deployment:
  pip install -r requirements.txt
  (cPanel runs this automatically)
"""

import sys
import os

# Ensure the app directory is on the path
_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

# Import the FastAPI app
from main import app as fastapi_app  # noqa: E402

# Wrap ASGI → WSGI using a2wsgi
try:
    from a2wsgi import ASGIMiddleware
    application = ASGIMiddleware(fastapi_app)
except ImportError:
    # Fallback: plain error page if a2wsgi not installed
    def application(environ, start_response):
        body = b"<h1>Server Error</h1><p>a2wsgi not installed. Run: pip install a2wsgi</p>"
        start_response("500 Internal Server Error", [
            ("Content-Type", "text/html"),
            ("Content-Length", str(len(body))),
        ])
        return [body]
