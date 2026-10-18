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
    monkeypatch.setattr('utils.account_socket.socket_session_active', lambda username: True)
    socket = Mock()
    register_account_socket(socket)
    handler = next(call.args[1] for call in socket.on_event.call_args_list if call.args[0] == 'connect')
    app = Flask(__name__)
    app.secret_key = 'synthetic'
    with app.test_request_context('/'):
        assert handler({'username': 'alice'}) is False
        session.update(user='alice', logged_in=True)
        from flask import request
        request.sid = 'synthetic-sid'
        handler({'username': 'bob'})
        join.assert_called_once_with(room_for('alice'))


def test_direct_account_delivery(monkeypatch):
    from utils.account_socket import emit_account
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    socket = Mock()
    emit_account(socket, 'alice', 'pending_order_updated', {'order_id': 1})
    socket.emit.assert_called_once_with('pending_order_updated', {'order_id': 1}, to=room_for('alice'), namespace='/')
    socket.reset_mock()
    emit_account(socket, None, 'pending_order_updated', {})
    socket.emit.assert_not_called()


def test_action_center_emit_sites_have_explicit_session_owner():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'blueprints/orders.py').read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'emit_account']
    assert len(calls) == 5
    for call in calls:
        assert isinstance(call.args[1], ast.Name) and call.args[1].id == 'login_username'
        assert call.args[2].value == 'pending_order_updated'
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'socketio' and node.func.attr == 'emit' for node in ast.walk(tree))
