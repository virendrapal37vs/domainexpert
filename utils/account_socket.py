"""Account-scoped delivery for order-event subscribers."""
import hashlib
import os
import threading
from datetime import datetime, timedelta
import pytz


def enabled():
    return os.getenv('DOMAINXPERT_PER_USER_GROWW', 'false').lower() == 'true'


def room_for(username):
    if not isinstance(username, str) or not username:
        raise ValueError('Account required')
    return 'account:' + hashlib.sha256(username.encode()).hexdigest()


def emit_order(socketio, event, name, payload):
    if not enabled():
        socketio.emit(name, payload)
        return
    from database.auth_db import get_username_by_apikey
    api_key = getattr(event, 'api_key', None)
    if not api_key:
        return
    username = get_username_by_apikey(api_key)
    if not username:
        return
    from utils.subscription_access import subscription_access_allowed
    if not subscription_access_allowed(username):
        return
    prune_account_sockets(socketio, username)
    socketio.emit(name, payload, to=room_for(username), namespace='/')


def register_account_socket(socketio):
    from flask import session, request
    from flask_socketio import join_room
    socketio._account_connections = {}
    socketio._account_connection_lock = threading.RLock()

    def connect(auth=None):
        if not enabled():
            return None
        from utils.account_access import current_account
        account = current_account()
        if account is None or not session.get('logged_in') or not socket_session_active(account.username):
            return False
        from utils.subscription_access import subscription_access_allowed
        if not subscription_access_allowed(account.username):
            return False
        join_room(room_for(account.username))
        with socketio._account_connection_lock:
            socketio._account_connections[request.sid] = {
                'username': account.username, 'session_id': session.get('session_id'),
                'expires_at': socket_expiry_deadline(),
            }
        return None

    def disconnected(reason=None):
        with socketio._account_connection_lock:
            socketio._account_connections.pop(request.sid, None)

    socketio.on_event('connect', connect, namespace='/')
    socketio.on_event('disconnect', disconnected, namespace='/')


def emit_account(socketio, username, name, payload):
    """Internal callers must pass an owner from a validated session/DB record."""
    if not enabled():
        socketio.emit(name, payload)
        return
    if not isinstance(username, str) or not username:
        return
    from utils.subscription_access import subscription_access_allowed
    if not subscription_access_allowed(username):
        return
    prune_account_sockets(socketio, username)
    socketio.emit(name, payload, to=room_for(username), namespace='/')


def socket_session_active(username):
    """Reject expired/revoked browser cookies before joining a private room."""
    from flask import session
    session_id = session.get('session_id')
    if not isinstance(session_id, str) or not session_id:
        return False
    from database.auth_db import ActiveSession, db_session
    try:
        from utils.session import is_session_valid
        return bool(is_session_valid() and ActiveSession.query.filter_by(
            username=username, session_id=session_id).first())
    except Exception:
        return False
    finally:
        db_session.remove()


def emit_session_event(socketio, username, name, payload):
    """Account-scoped session notifications; force logout closes owned sockets."""
    if not enabled():
        socketio.emit(name, payload)
        return
    if not isinstance(username, str) or not username:
        return
    if name != 'force_logout':
        emit_account(socketio, username, name, payload)
        return
    # This non-sensitive logout message precedes disconnect even after the DB
    # session was revoked; normal private payloads still require validation.
    socketio.emit(name, payload, to=room_for(username), namespace='/')
    if name == 'force_logout':
        participants = list(socketio.server.manager.get_participants('/', room_for(username)))
        for sid, _engine_sid in participants:
            socketio.server.disconnect(sid, namespace='/')


def socket_expiry_deadline():
    """Next configured IST rollover, after connect already checked login time."""
    if os.getenv('DISABLE_SESSION_EXPIRY', 'false').lower() == 'true':
        return None
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    hour, minute = map(int, os.getenv('SESSION_EXPIRY_TIME', '03:00').split(':'))
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= deadline:
        deadline += timedelta(days=1)
    return deadline.timestamp()


def prune_account_sockets(socketio, username):
    """Before private delivery, disconnect expired/revoked recipients only."""
    connections = getattr(socketio, '_account_connections', None)
    if not isinstance(connections, dict):
        return
    with socketio._account_connection_lock:
        candidates = [(sid, dict(identity)) for sid, identity in connections.items()
                      if identity['username'] == username]
    from database.auth_db import ActiveSession, db_session
    invalid = []
    now = datetime.now(pytz.UTC).timestamp()
    try:
        for sid, identity in candidates:
            try:
                deadline = identity['expires_at']
                active = deadline is None or now < deadline
                if active:
                    active = bool(ActiveSession.query.filter_by(
                        username=username, session_id=identity['session_id']).first())
            except Exception:
                # DB validation failure must not permit private payload delivery.
                active = False
            if not active:
                invalid.append(sid)
    finally:
        db_session.remove()
    for sid in invalid:
        socketio.server.disconnect(sid, namespace='/')
