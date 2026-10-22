"""Own-account credentials API. Keep signup closed until the tenant audit completes."""
from flask import Blueprint, jsonify, request, session
from limiter import limiter
from database.account_broker_db import (
    has_groww_credentials, per_user_groww_enabled, save_groww_credentials,
)
from utils.account_access import require_account
from pathlib import Path

account_broker_bp = Blueprint("account_broker", __name__, url_prefix="/api/account/brokers")


@account_broker_bp.post("/groww/check")
@require_account
@limiter.limit("3 per minute;10 per hour")
def groww_connection_check():
    """Transient authentication and one quote; never establish a trading session."""
    from utils.staging_mode import staging_safe, validate_staging_config
    if not staging_safe() or not per_user_groww_enabled():
        return jsonify(status="error", message="Read-only check is available in restricted staging only."), 403
    validate_staging_config(Path(__file__).resolve().parents[1])
    from database.account_broker_db import get_groww_credentials
    credentials = get_groww_credentials(session["user"])
    if not credentials:
        return jsonify(status="error", message="Save your own Groww credentials first."), 409
    from tenant_preview.groww_probe import check_connection
    result = check_connection(*credentials)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@account_broker_bp.route("/groww", methods=["GET", "PUT"])
@require_account
@limiter.limit("10 per minute")
def groww_credentials():
    if not per_user_groww_enabled():
        return jsonify(status="error", message="Per-account Groww credentials are disabled"), 404
    username = session["user"]
    if request.method == "GET":
        response = jsonify(status="success", configured=has_groww_credentials(username))
    else:
        # Do not silently rotate credentials underneath a live broker session.
        if session.get("logged_in"):
            return jsonify(status="error", message="Sign out and sign in again before changing broker credentials"), 409
        if not request.is_json or (request.content_length or 0) > 16384:
            return jsonify(status="error", message="Send a small JSON credentials object"), 400
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(status="error", message="Invalid credentials"), 400
        key, secret = data.get("api_key"), data.get("api_secret")
        if not all(isinstance(v, str) and v.strip() and len(v) <= 4096 for v in (key, secret)):
            return jsonify(status="error", message="API key and secret are required"), 400
        save_groww_credentials(username, key.strip(), secret.strip())
        response = jsonify(status="success", configured=True)
    response.headers["Cache-Control"] = "no-store"
    return response
