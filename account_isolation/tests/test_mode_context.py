import sys
from types import SimpleNamespace
import pytest
from flask import Flask, session
from utils.account_mode_context import resolve_mode_owner


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setitem(sys.modules, 'database.auth_db', SimpleNamespace(verify_api_key=lambda key: {'a-key': 'alice', 'b-key': 'bob'}.get(key)))
    monkeypatch.setitem(sys.modules, 'database.user_db', SimpleNamespace(find_user_by_exact_username=lambda name: name if name in ('alice', 'bob') else None))
    app = Flask(__name__)
    app.secret_key = 'test'
    return app


def test_browser_uses_session(app):
    with app.test_request_context('/orders/positions'):
        session['user'] = 'alice'
        assert resolve_mode_owner() == 'alice'


def test_api_uses_key_over_session(app):
    with app.test_request_context('/api/v1/placeorder', json={'apikey': 'b-key', 'username': 'alice'}):
        session['user'] = 'alice'
        assert resolve_mode_owner() == 'bob'


@pytest.mark.parametrize('data', [{}, {'apikey': 'invalid'}])
def test_api_cannot_fall_back_to_browser(app, data):
    with app.test_request_context('/api/v1/placeorder', json=data):
        session['user'] = 'alice'
        with pytest.raises(ValueError):
            resolve_mode_owner()


def test_background_needs_explicit_owner(app):
    with pytest.raises(ValueError):
        resolve_mode_owner()
    assert resolve_mode_owner(api_key='b-key') == 'bob'
    with pytest.raises(ValueError):
        resolve_mode_owner(username='alice', api_key='b-key')


def test_unknown_owner_rejected(app):
    with pytest.raises(ValueError):
        resolve_mode_owner(username='missing')
