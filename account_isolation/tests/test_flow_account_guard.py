"""Refuse unowned Flow APIs and direct execution before shared state is read."""
from flask import Flask, jsonify
import pytest
from test_strategy_account_guard import function


@pytest.fixture(autouse=True)
def scoped(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')


@pytest.mark.parametrize('path,verb', [('/flow/api/workflows', 'get'),
    ('/flow/api/workflows', 'post'), ('/flow/webhook/secret', 'post')])
def test_flow_http_guard(path, verb):
    app = Flask(__name__)
    app.before_request(function('blueprints/flow.py', 'require_account_safe_flow', {'jsonify': jsonify}))
    app.add_url_rule(path, view_func=lambda: {'ran': True}, methods=[verb.upper()])
    response = getattr(app.test_client(), verb)(path)
    assert response.status_code == 503
    assert response.json['code'] == 'FLOW_ACCOUNT_ISOLATION_PENDING'


def test_direct_workflow_refused_before_lock_or_broker():
    fn = function('services/flow_executor_service.py', 'execute_workflow', {})
    assert fn(1, api_key='fake-key')['code'] == 'FLOW_ACCOUNT_ISOLATION_PENDING'


def test_scheduled_workflow_returns_before_service_import_or_db():
    fn = function('services/flow_scheduler_service.py', 'execute_workflow_scheduled', {})
    assert fn(1, api_key='fake-key') is None


def test_legacy_http_guard_allows_existing_behavior(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    fn = function('blueprints/flow.py', 'require_account_safe_flow', {})
    assert fn() is None
