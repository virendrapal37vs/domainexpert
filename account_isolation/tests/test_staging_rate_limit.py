"""Real limiter rejection through the shipped app handler, without app startup."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from flask import Flask


def make_app(monkeypatch, restricted):
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', str(restricted).lower())
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setenv('DOMAINXPERT_PAPER_PREVIEW', 'true')
    monkeypatch.setenv('DOMAINXPERT_GROWW_PAPER_PREVIEW', 'true')
    from limiter import limiter
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='limited-test', RATELIMIT_ENABLED=True)
    limiter.init_app(app)
    limiter.reset()
    # Load the exact nested handler rather than starting broker/background services.
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'app.py').read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'rate_limit_exceeded')
    node.decorator_list = []
    namespace = dict(logger=SimpleNamespace(warning=lambda *args: None))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'app.py', 'exec'), namespace)
    app.register_error_handler(429, namespace['rate_limit_exceeded'])
    calls = []
    def action():
        calls.append('called')
        return {'ok': True}
    for path, endpoint in [('/paper-preview/groww/quote', 'paper_preview.groww_quote'),
                           ('/auth/signup', 'account_signup.signup'),
                           ('/api/account/brokers/groww/check', 'account_broker.groww_connection_check')]:
        app.add_url_rule(path, endpoint=endpoint, view_func=limiter.limit('1 per hour')(action), methods=['POST'])
    from utils import account_access
    monkeypatch.setattr(account_access, 'current_account', lambda: SimpleNamespace(username='alice'))
    from utils.staging_mode import install_staging_gate
    install_staging_gate(app)
    app.add_url_rule('/trade', endpoint='orders.live', view_func=action)
    return app, calls


@pytest.mark.parametrize('path,json_request', [('/paper-preview/groww/quote', False), ('/paper-preview/groww/quote', True), ('/auth/signup', True), ('/api/account/brokers/groww/check', True)])
def test_actual_rejection_stays_429_without_redirect(monkeypatch, path, json_request):
    app, calls = make_app(monkeypatch, True)
    client = app.test_client()
    kwargs = {'json': {}} if json_request else {'data': {'action': 'BUY'}}
    assert client.post(path, **kwargs).status_code == 200
    response = client.post(path, **kwargs)
    assert response.status_code == 429
    assert 'Location' not in response.headers
    assert response.headers['Cache-Control'] == 'no-store'
    # The hour limit is reported from the active limiter, not guessed as 60s.
    assert 3500 < int(response.headers['Retry-After']) <= 3602
    if json_request:
        assert response.json['status'] == 'error'
        assert response.json['retry_after'] == int(response.headers['Retry-After'])
    else:
        assert b'Too many requests' in response.data and b'Back to account' in response.data
    assert calls == ['called']
    assert client.get('/trade').status_code == 403
    assert calls == ['called']


def test_nonstaging_behavior_preserved(monkeypatch):
    app, calls = make_app(monkeypatch, False)
    client = app.test_client()
    url = '/paper-preview/groww/quote'
    assert client.post(url).status_code == 200
    response = client.post(url)
    assert response.status_code == 302 and response.headers['Location'] == '/rate-limited'
    url = '/api/account/brokers/groww/check'
    assert client.post(url).status_code == 200
    response = client.post(url)
    assert response.status_code == 429 and response.json['retry_after'] == 60


def test_no_current_window_has_clear_fallback(monkeypatch):
    app, _ = make_app(monkeypatch, True)
    from utils.staging_rate_limit import rate_limit_response
    with app.test_request_context('/auth/signup', method='POST'):
        response = rate_limit_response()
        assert response.status_code == 429
        assert response.json['message'].startswith('Too many requests.')
        assert 'Location' not in response.headers
