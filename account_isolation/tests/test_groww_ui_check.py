"""HTTP check uses session owner, CSRF and no persisted broker session."""
import importlib
import pytest


def test_account_owned_check(main_app, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'true')
    staging = importlib.import_module('utils.staging_mode')
    validated = []
    monkeypatch.setattr(staging, 'validate_staging_config', lambda root: validated.append(root))
    store = importlib.import_module('database.account_broker_db')
    store.save_groww_credentials('alice', 'alice-key', 'alice-secret')
    store.save_groww_credentials('bob', 'bob-key', 'bob-secret')
    probe = importlib.import_module('tenant_preview.groww_probe')
    calls = []
    def check(key, secret):
        calls.append((key, secret))
        return dict(status='success', stage='quote', http_status=200, message='Checked; trading disabled.')
    monkeypatch.setattr(probe, 'check_connection', check)
    client = main_app.test_client()
    token = client.get('/csrf').json['csrf_token']
    assert client.post('/api/account/brokers/groww/check', headers={'X-CSRFToken': token}).status_code == 401
    for owner in ('alice', 'bob'):
        with client.session_transaction() as session:
            session['user'] = owner
        assert client.post('/api/account/brokers/groww/check').status_code == 400
        response = client.post('/api/account/brokers/groww/check', json={'username': 'other'}, headers={'X-CSRFToken': token})
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'secret' not in response.get_data(as_text=True)
        with client.session_transaction() as session:
            assert not session.get('logged_in')
            assert session['user'] == owner
    assert calls == [('alice-key', 'alice-secret'), ('bob-key', 'bob-secret')]
    assert len(validated) == 2
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'false')
    assert client.post('/api/account/brokers/groww/check', headers={'X-CSRFToken': token}).status_code == 403
    assert len(calls) == 2


def test_missing_credentials_and_rejection(main_app, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'true')
    staging = importlib.import_module('utils.staging_mode')
    monkeypatch.setattr(staging, 'validate_staging_config', lambda root: None)
    client = main_app.test_client()
    with client.session_transaction() as session:
        session['user'] = 'alice'
    csrf = client.get('/csrf').json['csrf_token']
    url = '/api/account/brokers/groww/check'
    assert client.post(url, headers={'X-CSRFToken': csrf}).status_code == 409
    store = importlib.import_module('database.account_broker_db')
    store.save_groww_credentials('alice', 'key', 'secret')
    probe = importlib.import_module('tenant_preview.groww_probe')
    monkeypatch.setattr(probe, 'check_connection', lambda *args: dict(status='error', stage='authentication', http_status=403, message='Groww refused.'))
    response = client.post(url, headers={'X-CSRFToken': csrf})
    assert response.json['status'] == 'error'
    assert response.json['http_status'] == 403
