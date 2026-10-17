"""Direct registration: always creates a normal account, never a broker session."""
import os
import re
from flask import Blueprint, jsonify, request
from email_validator import validate_email, EmailNotValidError
from limiter import limiter
from database.user_db import User, add_user, db_session

signup_bp = Blueprint("account_signup", __name__)

@signup_bp.post("/auth/signup")
@limiter.limit("5 per hour")
def signup():
    if os.getenv("DOMAINXPERT_PUBLIC_SIGNUP", "false").lower() != "true":
        return jsonify(status="error", message="Sign up is currently unavailable."), 403
    if not db_session.query(User.id).first():
        return jsonify(status="error", message="Complete administrator setup first."), 409
    if not request.is_json or (request.content_length or 0) > 8192:
        return jsonify(status="error", message="Invalid registration request."), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(status="error", message="Invalid registration request."), 400
    username, email, password = (data.get(k) for k in ("username", "email", "password"))
    if not isinstance(username, str) or not re.fullmatch(r"[a-z0-9_]{3,40}", username):
        return jsonify(status="error", message="Username: 3–40 lowercase letters, numbers or underscores."), 400
    if not isinstance(email, str) or len(email) > 120:
        return jsonify(status="error", message="Enter a valid email address."), 400
    try:
        email = validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return jsonify(status="error", message="Enter a valid email address."), 400
    if not isinstance(password, str) or not 8 <= len(password) <= 128 or not all(re.search(pattern, password) for pattern in (r"[A-Z]", r"[a-z]", r"[0-9]", r"[!@#$%^&*]")):
        return jsonify(status="error", message="Use 8–128 characters with uppercase, lowercase, number and a special character (!@#$%^&*)."), 400
    if password != data.get("confirm_password"):
        return jsonify(status="error", message="Passwords do not match."), 400
    # Ignore all caller-supplied roles, IDs and broker credentials.
    if add_user(username, email, password, is_admin=False) is None:
        return jsonify(status="error", message="Username or email unavailable."), 409
    response = jsonify(status="success", message="Account created. Sign in to continue.")
    response.headers["Cache-Control"] = "no-store"
    return response, 201
