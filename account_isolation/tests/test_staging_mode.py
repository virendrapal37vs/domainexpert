import ast
from pathlib import Path

import pytest
from flask import Flask
from utils.staging_mode import install_staging_gate, staging_safe, validate_staging_config


@pytest.fixture
def staging_env(tmp_path, monkeypatch):
    values = {
        "DOMAINXPERT_STAGING_SAFE": "true", "DOMAINXPERT_PER_USER_GROWW": "true",
        "FLASK_HOST_IP": "127.0.0.1", "FLASK_PORT": "5001",
        "WEBSOCKET_HOST": "127.0.0.1", "WEBSOCKET_PORT": "8766",
        "ZMQ_HOST": "127.0.0.1", "ZMQ_PORT": "5556",
        "SESSION_COOKIE_NAME": "domainxpert_staging", "CSRF_COOKIE_NAME": "domainxpert_staging_csrf",
        "HOST_SERVER": "http://127.0.0.1:5001", "BROKER_API_KEY": "", "BROKER_API_SECRET": "",
        "FLASK_DEBUG": "False", "NGROK_ALLOW": "FALSE", "ORDER_UPDATES_ENABLED": "FALSE", "MCP_HTTP_ENABLED": "False",
        "HISTORIFY_DATABASE_URL": "db/staging-historify.duckdb",
    }
    for name in ("DATABASE_URL", "LATENCY_DATABASE_URL", "LOGS_DATABASE_URL", "HEALTH_DATABASE_URL", "SANDBOX_DATABASE_URL"):
        values[name] = "sqlite:///db/staging-" + name.lower() + ".db"
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return tmp_path


def test_staging_config_valid(staging_env):
    assert staging_safe()
    validate_staging_config(staging_env)


@pytest.mark.parametrize("name,value", [
    ("DATABASE_URL", "sqlite:///db/openalgo.db"),
    ("DATABASE_URL", "sqlite:////home/ubuntu/openalgo/db/staging-main.db"),
    ("DATABASE_URL", "postgresql://localhost/prod"),
    ("HISTORIFY_DATABASE_URL", "../openalgo/db/staging-history.duckdb"),
    ("FLASK_PORT", "5000"), ("FLASK_HOST_IP", "0.0.0.0"),
    ("WEBSOCKET_PORT", "8765"), ("ZMQ_PORT", "5555"),
    ("BROKER_API_KEY", "production-key"), ("MCP_HTTP_ENABLED", "True"),
    ("SESSION_COOKIE_NAME", "session"), ("NGROK_ALLOW", "TRUE"),
])
def test_unsafe_config_refused(staging_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        validate_staging_config(staging_env)


def test_gate_uses_resolved_endpoint_not_path_prefix(staging_env):
    app = Flask(__name__)
    install_staging_gate(app)
    app.add_url_rule('/login', endpoint='auth.login', view_func=lambda: 'ok')
    for path, name in [("/api/v1/placeorder", "orders.place"), ("/groww/callback", "brlogin.broker_callback"),
                       ("/socket.io/", "socket"), ("/auth/anything", "auth.unreviewed"), ("/admin", "admin.index")]:
        app.add_url_rule(path, endpoint=name, view_func=lambda: 'must not run', methods=['GET', 'POST'])
    client = app.test_client()
    assert client.get('/login').status_code == 200
    for path in ['/api/v1/placeorder', '/groww/callback', '/socket.io/', '/auth/anything', '/admin', '/unknown']:
        assert client.get(path).status_code == 403
        assert client.post(path).status_code == 403


def test_production_default_does_not_enable_staging(monkeypatch, tmp_path):
    monkeypatch.delenv('DOMAINXPERT_STAGING_SAFE', raising=False)
    assert not staging_safe()
    validate_staging_config(tmp_path)


def test_app_start_calls_are_guarded_and_schedulers_return_early():
    root = Path(__file__).resolve().parents[2]
    source = (root / 'app.py').read_text()
    tree = ast.parse(source)
    for name in ['start_hub_worker', 'start_websocket_proxy', 'start_drain_watcher',
                 'init_health_monitoring', 'start_broker_keepalive', 'start_order_update_adapters_on_boot']:
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]
        assert calls
        guarded = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and ast.unparse(node.test) == 'not staging_safe()':
                guarded.extend(n for child in node.body for n in ast.walk(child) if isinstance(n, ast.Call))
        assert all(call in guarded for call in calls), name
    assert source.index('if staging_safe():\n                app.db_ready.set()') < source.index('            for _attempt in range(1, 4):')


def test_socket_middleware_is_blocked_before_it_runs(staging_env):
    from utils.staging_mode import install_staging_socket_gate
    app = Flask(__name__)
    called = []
    original = app.wsgi_app
    def socket_middleware(environ, start_response):
        called.append(environ['PATH_INFO'])
        return original(environ, start_response)
    app.wsgi_app = socket_middleware
    install_staging_socket_gate(app)
    assert app.test_client().get('/socket.io/?transport=polling').status_code == 403
    assert app.test_client().get('/ws').status_code == 403
    assert called == []
