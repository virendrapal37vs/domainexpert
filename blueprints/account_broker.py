"""Own-account credentials API. Keep signup closed until the tenant audit completes."""
from flask import Blueprint, jsonify, request, session
from limiter import limiter
from database.account_broker_db import (
    has_groww_credentials, per_user_groww_enabled, save_groww_credentials,
)
from utils.account_access import require_account

account_broker_bp = Blueprint("account_broker", __name__, url_prefix="/api/account/brokers")


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
