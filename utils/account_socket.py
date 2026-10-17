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
        if account is None or not session.get('logged_in'):
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
