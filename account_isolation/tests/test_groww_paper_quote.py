import importlib
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture
def provider(monkeypatch):
    service = importlib.import_module('services.groww_paper_quote')
    monkeypatch.setattr(service.time, 'time', lambda: 1800000000)
    state = dict(auth=[], calls=[], token='private-token', payload=dict(last_price=400, last_trade_time=1799999990, ohlc=dict(low=390, high=410)))
    def auth(code, *, credentials):
        state['auth'].append(credentials)
        return state['token'], 'private-secret'
    def request(client, method, url, category, **kwargs):
        state['calls'].append((method, url, kwargs))
        return SimpleNamespace(status_code=state.get('http_status', 200), json=lambda: dict(status='SUCCESS', payload=state['payload']))
    monkeypatch.setitem(sys.modules, 'broker.groww.api.auth_api', SimpleNamespace(authenticate_broker=auth))
    monkeypatch.setitem(sys.modules, 'broker.groww.api.rate_limiter', SimpleNamespace(groww_request=request))
    monkeypatch.setitem(sys.modules, 'utils.httpx_client', SimpleNamespace(get_httpx_client=lambda: object()))
    return service, state


def test_fixed_quote_uses_owner_and_only_read_endpoint(provider):
    service, state = provider
    quote, error = service.fetch_quote(('owner-key', 'owner-secret'))
    assert not error and quote['ltp'] == 400 and quote['age_seconds'] == 10
    assert state['auth'] == [('owner-key', 'owner-secret')]
    method, url, kwargs = state['calls'][0]
    assert method == 'GET' and url == 'https://api.groww.in/v1/live-data/quote'
    assert kwargs['params'] == dict(exchange='NSE', segment='CASH', trading_symbol='BHEL')
    assert kwargs['timeout'] == 15
    assert 'private-token' not in str(quote)


@pytest.mark.parametrize('field,value', [('last_trade_time', 1799999800), ('last_trade_time', 1800000100), ('last_trade_time', 1800000000000), ('last_trade_time', None), ('last_price', float('nan')), ('last_price', True), ('last_price', -1), ('last_price', 450)])
def test_bad_and_stale_quotes_fail_closed(provider, field, value):
    service, state = provider
    state['payload'][field] = value
    quote, error = service.fetch_quote(('key', 'secret'))
    assert quote is None and error
    assert 'private-token' not in error and 'private-secret' not in error


def test_auth_failure_never_fetches_quote(provider):
    service, state = provider
    state['token'] = None
    quote, error = service.fetch_quote(('key', 'secret'))
    assert quote is None and error
    assert state['calls'] == []
