"""Password-authenticated account checks (usable before broker authentication)."""
from functools import wraps
from flask import jsonify, session


def current_account():
    username = session.get("user")
    if not isinstance(username, str) or not username:
        return None
    from database.user_db import find_user_by_exact_username
    return find_user_by_exact_username(username)


def require_account(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if current_account() is None:
            return jsonify(status="error", message="Sign in first"), 401
        return fn(*args, **kwargs)
    return wrapped


def require_instance_admin():
    """Blueprint before_request hook. Never trust a cookie's role field."""
    user = current_account()
    if user is None:
        return jsonify(status="error", message="Sign in first"), 401
    if not user.is_admin:
        return jsonify(status="error", message="Administrator access required"), 403
    return None
