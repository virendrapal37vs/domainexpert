"""Only synthetic databases/keys; full OpenAlgo startup is deliberately not run."""
import importlib
import sys
import pytest
from flask import Flask
from flask_wtf.csrf import CSRFProtect


@pytest.fixture(autouse=True)
def isolated_subscription_flags(monkeypatch):
    # Individual billing fixtures opt in; never inherit deployed billing flags.
    monkeypatch.setenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', 'false')
    monkeypatch.setenv('DOMAINXPERT_RAZORPAY_TEST', 'false')


@pytest.fixture
def main_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "main-test.db"))
    monkeypatch.setenv("API_KEY_PEPPER", "ab" * 32)
    monkeypatch.setenv("FERNET_SALT", "cd" * 32)
    monkeypatch.setenv("DOMAINXPERT_PER_USER_GROWW", "true")
    # Modules own scoped SQLAlchemy sessions; ensure each test uses its new DB.
    for name in ("blueprints.account_broker", "database.account_broker_db", "database.user_db", "database.auth_db"):
        module = sys.modules.pop(name, None)
        if module and hasattr(module, "db_session"):
            module.db_session.remove()
    users = importlib.import_module("database.user_db")
    users.Base.metadata.create_all(users.engine)
    users.add_user("alice", "alice@example.com", "fake-password-123", is_admin=True)
    users.add_user("bob", "bob@example.com", "fake-password-123")
    credentials = importlib.import_module("database.account_broker_db")
    credentials.init_account_broker_db()
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="unit-tests-only-" * 4, RATELIMIT_ENABLED=False)
    CSRFProtect(app)
    from flask_wtf.csrf import generate_csrf
    @app.get("/csrf")
    def csrf():
        return {"csrf_token": generate_csrf()}
    from limiter import limiter
    limiter.init_app(app)
    app.register_blueprint(importlib.import_module("blueprints.account_broker").account_broker_bp)
    from utils.account_access import require_instance_admin
    @app.get("/instance-setting")
    def protected():
        return require_instance_admin() or {"ok": True}
    yield app
    users.db_session.remove()
    credentials.engine.dispose()
