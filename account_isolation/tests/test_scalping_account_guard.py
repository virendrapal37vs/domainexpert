import ast
import __future__
from pathlib import Path
from unittest.mock import Mock
import pytest
from flask import Flask, jsonify

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def scoped(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')


@pytest.mark.parametrize('name,args', [('start', ()), ('request_sync', ()), ('sync', ()), ('_on_tick', ({'symbol': 'BHEL'},)), ('_exit_worker', ('key', {}, 'stop', 42)), ('_mode', ()), ('_resolve_api_key', ()), ('_resolve_auth', ())])
def test_monitor_cannot_use_first_user_or_run(name, args):
    tree = ast.parse((ROOT / 'services/scalping_risk_monitor_service.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ScalpingRiskMonitor')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    env = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<real-monitor-method>', 'exec', flags=__future__.annotations.compiler_flag), env)
    monitor = Mock()
    assert env[name](monitor, *args) is None
    assert monitor.mock_calls == []


def test_scalping_api_returns_explicit_unavailable(monkeypatch):
    tree = ast.parse((ROOT / 'blueprints/scalping.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'require_account_safe_scalping')
    fn.decorator_list = []
    env = {'jsonify': jsonify}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<real-scalping-gate>', 'exec'), env)
    app = Flask(__name__)
    app.before_request(env[fn.name])
    @app.post('/scalping/api/sl')
    def save_sl():
        return {'saved': True}
    client = app.test_client()
    response = client.post('/scalping/api/sl', json={})
    assert response.status_code == 503
    assert response.json['code'] == 'SCALPING_ACCOUNT_ISOLATION_PENDING'
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    assert client.post('/scalping/api/sl', json={}).status_code == 200
