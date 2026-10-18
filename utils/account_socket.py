"""Account-scoped delivery for order-event subscribers."""
import hashlib
import os


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
    socketio.emit(name, payload, to=room_for(username), namespace='/')


def register_account_socket(socketio):
    from flask import session
    from flask_socketio import join_room

    def connect(auth=None):
        if not enabled():
            return None
        from utils.account_access import current_account
        account = current_account()
        if account is None or not session.get('logged_in') or not socket_session_active(account.username):
            return False
        join_room(room_for(account.username))
        return None

    socketio.on_event('connect', connect, namespace='/')


def emit_account(socketio, username, name, payload):
    """Internal callers must pass an owner from a validated session/DB record."""
    if not enabled():
        socketio.emit(name, payload)
        return
    if not isinstance(username, str) or not username:
        return
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
    emit_account(socketio, username, name, payload)
    if name == 'force_logout':
        participants = list(socketio.server.manager.get_participants('/', room_for(username)))
        for sid, _engine_sid in participants:
            socketio.server.disconnect(sid, namespace='/')
