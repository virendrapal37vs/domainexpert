"""Real Flask-SocketIO test clients; fake API keys and synthetic order events."""
import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture
def transport(main_app, monkeypatch):
    from flask_socketio import SocketIO
    from utils.account_socket import register_account_socket
    socket = SocketIO(main_app, async_mode='threading')
    register_account_socket(socket)
    auth = importlib.import_module('database.auth_db')
    monkeypatch.setattr(auth, 'get_username_by_apikey', lambda key: {'alice-key': 'alice', 'bob-key': 'bob'}.get(key))
    monkeypatch.setitem(sys.modules, 'extensions', SimpleNamespace(socketio=socket))
    # Load the real subscriber without package __init__, which starts unrelated
    # Telegram/WhatsApp/log subscribers. No external adapters belong in this test.
    source = Path(__file__).resolve().parents[2] / 'subscribers/socketio_subscriber.py'
    spec = importlib.util.spec_from_file_location('isolated_socket_subscriber', source)
    subscriber = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subscriber)
    sockets = {}
    http_clients = {}
    for owner in ('alice', 'bob'):
        http = main_app.test_client()
        with http.session_transaction() as session:
            session.update(user=owner, logged_in=True)
        http_clients[owner] = http
        # A claimed other username must not decide the room.
        sockets[owner] = socket.test_client(main_app, flask_test_client=http,
                                             auth={'username': 'bob' if owner == 'alice' else 'alice'})
        assert sockets[owner].is_connected()
    yield main_app, socket, sockets, http_clients, subscriber
    for client in sockets.values():
        if client.is_connected():
            client.disconnect()


def event(owner):
    return SimpleNamespace(mode='live', api_key=owner + '-key', symbol='BHEL',
                           action='BUY', orderid=owner + '-order', exchange='NSE',
                           pricetype='MARKET', product='MIS')


def test_real_transport_delivers_order_only_to_owner(transport):
    _app, _socket, clients, _http, subscriber = transport
    subscriber.on_order_placed(event('alice'))
    received = clients['alice'].get_received()
    assert [entry['name'] for entry in received] == ['order_event']
    assert received[0]['args'][0]['orderid'] == 'alice-order'
    assert clients['bob'].get_received() == []
    subscriber.on_order_placed(event('bob'))
    assert clients['bob'].get_received()[0]['args'][0]['orderid'] == 'bob-order'
    assert clients['alice'].get_received() == []


def test_direct_action_center_event_stays_private(transport):
    from utils.account_socket import emit_account
    _app, socket, clients, _http, _subscriber = transport
    emit_account(socket, 'bob', 'pending_order_updated', {'order_id': 'bob-pending'})
    assert clients['alice'].get_received() == []
    assert clients['bob'].get_received()[0]['args'][0]['order_id'] == 'bob-pending'


def test_anonymous_and_unknown_account_cannot_connect(transport):
    app, socket, _clients, _http, _subscriber = transport
    anonymous = socket.test_client(app, auth={'username': 'alice'})
    assert not anonymous.is_connected()
    fake_http = app.test_client()
    with fake_http.session_transaction() as session:
        session.update(user='does-not-exist', logged_in=True)
    unknown = socket.test_client(app, flask_test_client=fake_http)
    assert not unknown.is_connected()


def test_missing_broker_auth_rejected(transport):
    app, socket, _clients, _http, _subscriber = transport
    http = app.test_client()
    with http.session_transaction() as session:
        session['user'] = 'alice'
    client = socket.test_client(app, flask_test_client=http)
    assert not client.is_connected()


def test_invalid_key_event_is_not_broadcast(transport):
    _app, _socket, clients, _http, subscriber = transport
    subscriber.on_order_placed(event('invalid'))
    assert clients['alice'].get_received() == []
    assert clients['bob'].get_received() == []
