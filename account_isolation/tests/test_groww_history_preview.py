"""Fixed read-only history, session-owned credentials and safe response failures."""
import importlib
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture
def provider(monkeypatch):
    preview = importlib.import_module('services.groww_history_preview')
    state = dict(auth=[], history=[], rows=[dict(timestamp=1792554300, open=428.8, high=430.45, low=427.1, close=427.15, volume=776276)])
    def authenticate(code, *, credentials):
        state['auth'].append(credentials)
        return ('private-token', None) if not state.get('auth_error') else (None, 'private-secret')
    class Handler:
        def __init__(self, token):
            assert token == 'private-token'
        def get_history(self, *args):
            state['history'].append(args)
            if state.get('raise'):
                raise ValueError('private-token private-secret')
            return Frame()
    class Frame:
        def __len__(self):
            return len(state['rows'])
        def to_dict(self, orient):
            assert orient == 'records'
            return state['rows']
    monkeypatch.setitem(sys.modules, 'broker.groww.api.auth_api', SimpleNamespace(authenticate_broker=authenticate))
    monkeypatch.setitem(sys.modules, 'broker.groww.api.data', SimpleNamespace(BrokerData=Handler))
    return preview, state


def test_fixed_day_and_no_secret(provider):
    preview, state = provider
    result = preview.fetch_preview(('owner-key', 'owner-secret'))
    assert result['status'] == 'success' and result['count'] == 1
    assert result['trading_enabled'] is False
    assert state['auth'] == [('owner-key', 'owner-secret')]
    assert state['history'] == [('BHEL', 'NSE', '5m', result['date'], result['date'])]
    assert 'private-token' not in str(result) and 'owner-secret' not in str(result)
    assert result['candles'][0]['volume'] == 776276


@pytest.mark.parametrize('failure', ['auth_error', 'raise', 'invalid', 'too_many'])
def test_failures_hide_provider_details(provider, failure):
    preview, state = provider
    if failure == 'invalid':
        state['rows'][0]['close'] = float('nan')
    elif failure == 'too_many':
        state['rows'] *= 301
    else:
        state[failure] = True
    result = preview.fetch_preview(('key', 'private-secret'))
    assert result['status'] == 'error'
    assert 'private-token' not in str(result) and 'private-secret' not in str(result)
    assert 'candles' not in result
    if failure == 'auth_error':
        assert state['history'] == []


def test_empty_history_is_explicit(provider):
    preview, state = provider
    state['rows'] = []
    result = preview.fetch_preview(('key', 'secret'))
    assert result['status'] == 'success' and result['count'] == 0
    assert 'holiday' in result['message']


def test_http_owners_csrf_and_staging(main_app, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'true')
    staging = importlib.import_module('utils.staging_mode')
    monkeypatch.setattr(staging, 'validate_staging_config', lambda root: None)
    store = importlib.import_module('database.account_broker_db')
    service = importlib.import_module('services.groww_history_preview')
    calls = []
    def fetch(credentials):
        calls.append(credentials)
        return dict(status='success', count=0, candles=[], trading_enabled=False)
    monkeypatch.setattr(service, 'fetch_preview', fetch)
    client = main_app.test_client()
    url = '/api/account/brokers/groww/history-preview'
    csrf = client.get('/csrf').json['csrf_token']
    headers = {'X-CSRFToken': csrf}
    assert client.post(url, headers=headers).status_code == 401
    for owner in ('alice', 'bob'):
        with client.session_transaction() as session:
            session['user'] = owner
        assert client.post(url, headers=headers).status_code == 409
        store.save_groww_credentials(owner, owner + '-key', owner + '-secret')
        assert client.post(url).status_code == 400
        response = client.post(url, headers=headers, json={'username': 'other', 'symbol': 'RELIANCE', 'start': '2000-01-01'})
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        with client.session_transaction() as session:
            assert session['user'] == owner and not session.get('logged_in')
    assert calls == [('alice-key', 'alice-secret'), ('bob-key', 'bob-secret')]
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'false')
    assert client.post(url, headers=headers).status_code == 403
    assert len(calls) == 2
