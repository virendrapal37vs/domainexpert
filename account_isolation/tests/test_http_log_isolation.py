"""Real log blueprints/SQLite over Flask HTTP; broker session boundary stubbed."""
import importlib
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import pytz
from flask import jsonify


@pytest.fixture
def http_logs(main_app, monkeypatch):
    from utils.account_access import require_account
    monkeypatch.setitem(sys.modules, 'utils.session', SimpleNamespace(check_session_validity=require_account))
    monkeypatch.setitem(sys.modules, 'extensions', SimpleNamespace(socketio=Mock()))
    monkeypatch.setitem(sys.modules, 'database.symbol', SimpleNamespace(SymToken=Mock()))
    modules = {}
    for name in ('database.apilog_db', 'database.analyzer_db', 'utils.api_analyzer', 'blueprints.log', 'blueprints.analyzer'):
        sys.modules.pop(name, None)
        modules[name] = importlib.import_module(name)
    api = modules['database.apilog_db']
    analyzer = modules['database.analyzer_db']
    for module in (api, analyzer):
        module.Base.metadata.create_all(module.engine)
    from database.auth_db import verify_api_key
    monkeypatch.setattr(importlib.import_module('database.auth_db'), 'verify_api_key', lambda key: {'alice-key': 'alice', 'bob-key': 'bob'}.get(key))
    for owner in ('alice', 'bob'):
        payload = {'symbol': owner.upper() + '_ONLY', 'exchange': 'NSE', 'strategy': owner, 'quantity': 1}
        api.async_log_order('placeorder', payload, {'status': 'success'}, api_key=owner + '-key')
        analyzer.async_log_analyzer(payload, {'status': 'success'}, api_key=owner + '-key')
    api.async_log_order('old', {'symbol': 'UNOWNED_ONLY'}, {})
    analyzer.async_log_analyzer({'symbol': 'UNOWNED_ONLY'}, {})
    main_app.register_blueprint(modules['blueprints.log'].log_bp)
    main_app.register_blueprint(modules['blueprints.analyzer'].analyzer_bp)
    clients = {owner: main_app.test_client() for owner in ('alice', 'bob')}
    for owner, client in clients.items():
        with client.session_transaction() as session:
            session['user'] = owner
    yield main_app, clients, api, analyzer
    for module in (api, analyzer):
        module.db_session.remove()
        module.executor.shutdown(wait=True)
        module.engine.dispose()


@pytest.mark.parametrize('owner,other', [('alice', 'bob'), ('bob', 'alice')])
def test_actual_api_log_http_list_and_export(http_logs, owner, other):
    _app, clients, _api, _analyzer = http_logs
    query = '?start_date=2000-01-01&end_date=2100-01-01&username=' + other
    response = clients[owner].get('/logs/' + query, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 200
    assert len(response.json['logs']) == 1
    assert response.json['logs'][0]['request_data']['symbol'] == owner.upper() + '_ONLY'
    export = clients[owner].get('/logs/export' + query)
    assert export.status_code == 200
    assert owner.upper() + '_ONLY' in export.text
    assert other.upper() + '_ONLY' not in export.text
    assert 'UNOWNED_ONLY' not in export.text


@pytest.mark.parametrize('owner,other', [('alice', 'bob'), ('bob', 'alice')])
def test_actual_analyzer_http_stats_and_export(http_logs, owner, other):
    _app, clients, _api, _analyzer = http_logs
    query = '?start_date=2000-01-01&end_date=2100-01-01&username=' + other
    response = clients[owner].get('/analyzer/api/data' + query)
    assert response.status_code == 200
    assert response.json['data']['stats']['total_requests'] == 1
    assert len(response.json['data']['requests']) == 1
    assert response.json['data']['requests'][0]['symbol'] == owner.upper() + '_ONLY'
    export = clients[owner].get('/analyzer/export' + query)
    assert export.status_code == 200
    assert owner.upper() + '_ONLY' in export.text
    assert other.upper() + '_ONLY' not in export.text
    assert 'UNOWNED_ONLY' not in export.text


def test_anonymous_export_rejected(http_logs):
    app, _clients, _api, _analyzer = http_logs
    client = app.test_client()
    assert client.get('/logs/export').status_code == 401
    assert client.get('/analyzer/export').status_code == 401


def test_actual_clear_requires_csrf_post_and_preserves_other_owner(http_logs):
    _app, clients, _api, analyzer = http_logs
    analyzer.db_session.query(analyzer.AnalyzerLog).update({'created_at': datetime.now(pytz.UTC) - timedelta(days=2)})
    analyzer.db_session.commit()
    client = clients['alice']
    assert client.get('/analyzer/clear').status_code == 405
    assert client.post('/analyzer/clear').status_code == 400
    assert analyzer.account_analyzer_query(username='alice').count() == 1
    csrf = client.get('/csrf').json['csrf_token']
    assert client.post('/analyzer/clear', headers={'X-CSRFToken': csrf}).status_code == 302
    assert analyzer.account_analyzer_query(username='alice').count() == 0
    assert analyzer.account_analyzer_query(username='bob').count() == 1
    assert analyzer.db_session.query(analyzer.AnalyzerLog).count() == 2
