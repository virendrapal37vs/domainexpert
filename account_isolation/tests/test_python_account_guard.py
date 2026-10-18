"""Guard actual Python-strategy entry points without loading schedulers/processes."""
from unittest.mock import Mock
from flask import Flask, jsonify
import pytest
from test_strategy_account_guard import function

FILE = 'blueprints/python_strategy.py'


@pytest.fixture(autouse=True)
def account_mode(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')


def test_python_http_routes_explicitly_unavailable(monkeypatch):
    app = Flask(__name__)
    guard = function(FILE, 'require_account_safe_python_strategy', {'jsonify': jsonify})
    app.before_request(guard)
    app.add_url_rule('/python/api/strategies', view_func=lambda: {'ran': True})
    app.add_url_rule('/python/start/other', endpoint='start', view_func=lambda: {'ran': True}, methods=['POST'])
    for response in (app.test_client().get('/python/api/strategies'),
                     app.test_client().post('/python/start/other')):
        assert response.status_code == 503
        assert response.json['code'] == 'PYTHON_ACCOUNT_ISOLATION_PENDING'
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    assert app.test_client().get('/python/api/strategies').status_code == 200


def test_direct_start_stops_before_process_or_environment_access():
    fn = function(FILE, 'start_strategy_process', {})
    ok, message = fn('alice-strategy')
    assert ok is False
    assert 'isolated account runner' in message


@pytest.mark.parametrize('name', ['initialize_with_app_context', '_initialize_locked'])
def test_no_background_restore_or_scheduler_initialization(name):
    assert function(FILE, name, {})() is None


def test_status_broadcast_drops_before_shared_queues():
    assert function(FILE, 'broadcast_status_update', {})('secret-id', 'running') is None


@pytest.mark.parametrize('owner,caller,allowed', [
    (None, 'alice', False), ('bob', 'alice', False), ('alice', None, False),
    ('alice', 'alice', True)])
def test_ownership_requires_exact_nonempty_owner(owner, caller, allowed):
    app = Flask(__name__)
    fn = function(FILE, 'verify_strategy_ownership', {
        'jsonify': jsonify, 'get_strategy_config': lambda sid: {'user_id': owner}})
    with app.app_context():
        ok, result = fn('strategy-1', caller)
    assert ok is allowed
    if not allowed:
        assert result[1] == 403
