"""Real book routes; fake broker/session boundaries, no live orders or tokens."""
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import jsonify, session


@pytest.fixture
def books(main_app, monkeypatch):
    from utils.account_access import require_account
    monkeypatch.setitem(sys.modules, 'utils.session', SimpleNamespace(check_session_validity=require_account))
    monkeypatch.setitem(sys.modules, 'utils.latency_monitor', SimpleNamespace(track_latency=lambda name: lambda fn: fn))
    auth = importlib.import_module('database.auth_db')
    monkeypatch.setattr(auth, 'get_auth_token', lambda user: 'token-' + user)
    monkeypatch.setattr(auth, 'get_api_key_for_tradingview', lambda user: 'key-' + user)
    monkeypatch.setitem(sys.modules, 'database.settings_db', SimpleNamespace(get_analyze_mode=lambda: session.get('user') == 'alice'))
    calls = {}
    def make_book(kind):
        def book(**kwargs):
            credential = kwargs.get('api_key') or kwargs.get('auth_token')
            owner = credential.split('-', 1)[1]
            data = [{'owner': owner, 'symbol': owner.upper() + '_ONLY'}]
            return True, {'data': {'orders': data} if kind == 'orders' else data}, 200
        calls[kind] = Mock(side_effect=book)
        return calls[kind]
    for module_name, func_name, func in [
        ('services.orderbook_service', 'get_orderbook', make_book('orders')),
        ('services.positionbook_service', 'get_positionbook', make_book('positions')),
        ('services.holdings_service', 'get_holdings', Mock()),
        ('services.tradebook_service', 'get_tradebook', Mock()),
        ('services.place_smart_order_service', 'place_smart_order', Mock()),
    ]:
        monkeypatch.setitem(sys.modules, module_name, SimpleNamespace(**{func_name: func}))
    sys.modules.pop('blueprints.orders', None)
    module = importlib.import_module('blueprints.orders')
    monkeypatch.setattr(module, 'render_template', lambda name, **data: jsonify(data))
    main_app.register_blueprint(module.orders_bp)
    clients = {user: main_app.test_client() for user in ('alice', 'bob')}
    for owner, client in clients.items():
        with client.session_transaction() as signed:
            signed.update(user=owner, broker='groww', logged_in=True)
    return main_app, clients, calls


@pytest.mark.parametrize('path,kind,field', [('/orderbook', 'orders', 'order_data'), ('/positions', 'positions', 'positions_data')])
def test_real_http_route_uses_session_owner(books, path, kind, field):
    _app, clients, calls = books
    for owner, other in [('alice', 'bob'), ('bob', 'alice')]:
        response = clients[owner].get(path + '?username=' + other)
        assert response.status_code == 200
        assert response.json[field][0]['owner'] == owner
        assert other.upper() + '_ONLY' not in response.text
        expected = {'api_key': 'key-alice'} if owner == 'alice' else {'auth_token': 'token-bob', 'broker': 'groww'}
        assert calls[kind].call_args.kwargs == expected


@pytest.mark.parametrize('path', ['/orderbook', '/positions'])
def test_anonymous_books_rejected(books, path):
    app, _clients, calls = books
    assert app.test_client().get(path).status_code == 401
    assert all(not mock.called for mock in calls.values())
