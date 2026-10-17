import sys
from types import SimpleNamespace
from unittest.mock import Mock
from utils.account_socket import emit_order, room_for, register_account_socket


def test_rooms_are_distinct():
    assert room_for('alice') != room_for('bob')
    assert 'alice' not in room_for('alice')


def test_scoped_emit(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setitem(sys.modules, 'database.auth_db', SimpleNamespace(get_username_by_apikey=lambda key: 'alice' if key == 'alice-key' else None))
    socket = Mock()
    emit_order(socket, SimpleNamespace(api_key='alice-key'), 'order_event', {'orderid': '1'})
    socket.emit.assert_called_once_with('order_event', {'orderid': '1'}, to=room_for('alice'), namespace='/')
    socket.reset_mock()
    for key in ('', 'invalid'):
        emit_order(socket, SimpleNamespace(api_key=key), 'order_event', {})
    socket.emit.assert_not_called()


def test_legacy_delivery(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    socket = Mock()
    emit_order(socket, SimpleNamespace(), 'order_event', {})
    socket.emit.assert_called_once_with('order_event', {})


def test_connection_uses_session_account_not_payload(monkeypatch):
    from flask import Flask, session
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    join = Mock()
    monkeypatch.setitem(sys.modules, 'flask_socketio', SimpleNamespace(join_room=join))
    monkeypatch.setitem(sys.modules, 'utils.account_access', SimpleNamespace(current_account=lambda: SimpleNamespace(username='alice') if session.get('user') else None))
    socket = Mock()
    register_account_socket(socket)
    handler = socket.on_event.call_args.args[1]
    app = Flask(__name__)
    app.secret_key = 'synthetic'
    with app.test_request_context('/'):
        assert handler({'username': 'alice'}) is False
        session.update(user='alice', logged_in=True)
        handler({'username': 'bob'})
        join.assert_called_once_with(room_for('alice'))
