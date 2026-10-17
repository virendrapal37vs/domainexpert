"""Restricted main-app onboarding staging, never a multi-user trading switch."""
import os
from pathlib import Path

from flask import jsonify, request


def staging_safe():
    return os.getenv("DOMAINXPERT_STAGING_SAFE", "false").lower() == "true"


def validate_staging_config(root):
    if not staging_safe():
        return
    root = Path(root).resolve()
    for name in ("DATABASE_URL", "LATENCY_DATABASE_URL", "LOGS_DATABASE_URL", "HEALTH_DATABASE_URL", "SANDBOX_DATABASE_URL"):
        value = os.getenv(name, "")
        if not value.startswith("sqlite:///"):
            raise RuntimeError(f"Staging requires a separate SQLite file for {name}")
        relative = Path(value[len("sqlite:///"):])
        path = (root / relative).resolve()
        if relative.is_absolute() or path.parent != root / "db" or not path.name.startswith("staging-"):
            raise RuntimeError(f"Staging requires {name} under this checkout's db/staging-* files")
    historify = (root / os.getenv("HISTORIFY_DATABASE_URL", "")).resolve()
    if historify.parent != root / "db" or not historify.name.startswith("staging-"):
        raise RuntimeError("Staging Historify path must be db/staging-*")
    expected = {"FLASK_HOST_IP": "127.0.0.1", "FLASK_PORT": "5001",
                "WEBSOCKET_HOST": "127.0.0.1", "WEBSOCKET_PORT": "8766",
                "ZMQ_HOST": "127.0.0.1", "ZMQ_PORT": "5556",
                "SESSION_COOKIE_NAME": "domainxpert_staging", "CSRF_COOKIE_NAME": "domainxpert_staging_csrf"}
    for name, value in expected.items():
        if os.getenv(name) != value:
            raise RuntimeError(f"Staging requires {name}={value}")
    if os.getenv("HOST_SERVER") != "http://127.0.0.1:5001":
        raise RuntimeError("Staging HOST_SERVER must be loopback port 5001")
    if os.getenv("BROKER_API_KEY") or os.getenv("BROKER_API_SECRET"):
        raise RuntimeError("Keep global broker credentials empty in staging")
    if os.getenv("DOMAINXPERT_PER_USER_GROWW", "").lower() != "true":
        raise RuntimeError("Enable the development per-user Groww path for staging")
    if os.getenv("FLASK_DEBUG", "").lower() != "false" or os.getenv("NGROK_ALLOW", "").lower() != "false":
        raise RuntimeError("Staging requires debugger and ngrok disabled")
    if os.getenv("ORDER_UPDATES_ENABLED", "").lower() != "false" or os.getenv("MCP_HTTP_ENABLED", "").lower() != "false":
        raise RuntimeError("Staging requires order adapters and MCP disabled")


STAGING_ENDPOINTS = frozenset({
    "react.react_index", "react.react_login", "react.react_setup", "react.react_broker",
    "react.serve_assets", "react.serve_favicon", "react.serve_logo",
    "react.serve_apple_touch_icon", "react.serve_images",
    "auth.login", "auth.login_totp", "auth.logout", "auth.get_csrf_token",
    "auth.check_setup_required", "auth.get_broker_config", "auth.get_session_status",
    "auth.get_app_info", "core_bp.setup", "account_broker.groww_credentials",
})


def install_staging_gate(app):
    @app.before_request
    def restricted_staging_routes():
        if staging_safe() and request.endpoint not in STAGING_ENDPOINTS:
            return jsonify(status="error", message="Staging permits account setup, login and credential storage only. Broker connections and trading are blocked."), 403


def install_staging_socket_gate(app):
    # Socket.IO's middleware handles its path before Flask before_request hooks.
    original = app.wsgi_app
    def guarded(environ, start_response):
        if staging_safe() and (environ.get("PATH_INFO", "").startswith("/socket.io") or environ.get("PATH_INFO", "").startswith("/ws")):
            from werkzeug.wrappers import Response
            return Response("WebSockets disabled in restricted staging", status=403)(environ, start_response)
        return original(environ, start_response)
    app.wsgi_app = guarded
