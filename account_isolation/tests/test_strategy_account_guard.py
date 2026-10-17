import ast
import __future__
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from flask import Flask, jsonify
import pytest

ROOT = Path(__file__).resolve().parents[2]


def function(file, name, env, cls=None):
    tree = ast.parse((ROOT / file).read_text())
    nodes = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls).body if cls else tree.body
    node = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<real-strategy-function>', 'exec', flags=__future__.annotations.compiler_flag), env)
    return env[name]


@pytest.fixture(autouse=True)
def scoped(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')


@pytest.mark.parametrize('name,args', [('_resolve_api_key', ()), ('_ensure_ws', ()), ('on_tick', ({'symbol': 'BHEL'},)), ('_emit_prices', ([('BHEL', 'NSE', 42)],))])
def test_shared_feed_cannot_use_first_user(name, args):
    fn = function('services/strategy_module/tick_feed.py', name, {}, cls='RiskTickFeed')
    feed = Mock()
    assert fn(feed, *args) is None
    assert feed.mock_calls == []


def test_direct_start_refuses_before_store_or_broker():
    store = Mock()
    fn = function('services/strategy_module/engine.py', 'start_run', {'store': store, 'StartResult': SimpleNamespace})
    result = fn(1, 'alice', 'live')
    assert result.ok is False
    store.assert_not_called()
    assert store.mock_calls == []


def test_runtime_starts_no_jobs():
    env = {'_started': False}
    fn = function('services/strategy_module/runtime.py', 'start_strategy_module', env)
    assert not any(fn().values())
    assert env['_started'] is False


def test_http_and_webhook_blocked_explicitly(monkeypatch):
    fn = function('blueprints/strategy_module.py', 'require_account_safe_strategy', {'jsonify': jsonify})
    app = Flask(__name__)
    app.before_request(fn)
    app.add_url_rule('/strategy/webhook/fake-token', view_func=lambda: {'ran': True}, methods=['POST'])
    client = app.test_client()
    response = client.post('/strategy/webhook/fake-token')
    assert response.status_code == 503
    assert response.json['code'] == 'STRATEGY_ACCOUNT_ISOLATION_PENDING'
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    assert client.post('/strategy/webhook/fake-token').status_code == 200
