"""Run standalone: python -m pytest -q -o addopts="" tenant_preview/tests --confcutdir=tenant_preview/tests"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from tenant_preview.app import create_app
from tenant_preview.store import Credential, Invitation, PreviewUser


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True, "SECRET_KEY": "test-session-key-" * 4,
        "PREVIEW_DATABASE": str(tmp_path / "preview.db"),
        "PREVIEW_ENCRYPTION_KEY": Fernet.generate_key(),
        "RATELIMIT_ENABLED": False,
    })


def send(client, path, method="POST", data=None):
    csrf = client.get("/preview/csrf").json["csrf_token"]
    return client.open("/preview/" + path, method=method, json=data,
                       headers={"X-CSRFToken": csrf})


def add_account(app, email):
    store = app.extensions["preview_store"]
    token = store.invite(email)
    client = app.test_client()
    assert send(client, "register", data={"email": email, "password": "a-test-password-123", "invitation": token}).status_code == 201
    assert send(client, "login", data={"email": email, "password": "a-test-password-123"}).status_code == 200
    return client


def test_credentials_are_isolated_even_with_forged_owner(app):
    alice = add_account(app, "alice@example.com")
    bob = add_account(app, "bob@example.com")
    result = send(alice, "credentials", "PUT", {"api_key": "alice-key", "api_secret": "alice-secret", "user_id": 2})
    assert result.status_code == 200
    assert "alice-key" not in result.text and "alice-secret" not in result.text
    assert send(alice, "credentials", "GET").json["configured"] is True
    assert send(bob, "credentials", "GET").json["configured"] is False
    assert send(bob, "credentials", "DELETE").status_code == 200
    assert send(alice, "credentials", "GET").json["configured"] is True
    assert send(bob, "credentials", "PUT", {"api_key": "bob-key", "api_secret": "bob-secret"}).status_code == 200
    send(alice, "credentials", "DELETE")
    assert send(bob, "credentials", "GET").json["configured"] is True


def test_ciphertext_and_passwords_are_not_plaintext(app):
    client = add_account(app, "alice@example.com")
    send(client, "credentials", "PUT", {"api_key": "private-key", "api_secret": "private-secret"})
    store = app.extensions["preview_store"]
    with store.sessions() as db:
        user = db.scalar(select(PreviewUser))
        row = db.scalar(select(Credential))
        assert user.password_hash.startswith("$argon2id$")
        assert "private-key" not in row.ciphertext and "private-secret" not in row.ciphertext
        assert b"private-secret" in store.cipher.decrypt(row.ciphertext.encode())


def test_unauthenticated_and_logout_cannot_access_credentials(app):
    client = app.test_client()
    for method in ("GET", "PUT", "DELETE"):
        assert send(client, "credentials", method, {}).status_code == 401
    client = add_account(app, "alice@example.com")
    send(client, "logout")
    assert send(client, "credentials", "GET").status_code == 401


def test_csrf_required_for_every_mutation(app):
    client = add_account(app, "alice@example.com")
    for path, method in [("register", "POST"), ("login", "POST"), ("logout", "POST"), ("credentials", "PUT"), ("credentials", "DELETE")]:
        assert client.open("/preview/" + path, method=method, json={}).status_code == 400


def test_invitation_email_binding_expiry_and_single_use(app):
    store = app.extensions["preview_store"]
    client = app.test_client()
    token = store.invite("alice@example.com")
    payload = {"email": "bob@example.com", "password": "password-long-123", "invitation": token}
    assert send(client, "register", data=payload).status_code == 400
    payload["email"] = "alice@example.com"
    assert send(client, "register", data=payload).status_code == 201
    assert send(client, "register", data=payload).status_code == 400
    token = store.invite("bob@example.com")
    with store.sessions.begin() as db:
        db.execute(update(Invitation).where(Invitation.email == "bob@example.com").values(expires_at=int(time.time()) - 1))
    payload.update(email="bob@example.com", invitation=token)
    assert send(client, "register", data=payload).status_code == 400


def test_parallel_invitation_consumption_creates_one_user(app):
    store = app.extensions["preview_store"]
    token = store.invite("alice@example.com")
    def register(_):
        try:
            store.register("alice@example.com", "parallel-test-password", token)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(register, range(2))) == [False, True]


def test_wrong_login_and_bad_payloads(app):
    client = add_account(app, "alice@example.com")
    send(client, "logout")
    assert send(client, "login", data={"email": "alice@example.com", "password": "wrong"}).status_code == 401
    assert send(client, "login", data={"email": "nobody@example.com", "password": "wrong"}).status_code == 401
    for payload in ([], {"email": 42}, {"email": "bad"}, {"email": "alice@example.com", "password": [1]}):
        assert send(client, "login", data=payload).status_code == 400


def test_no_trading_or_production_routes_and_no_cache(app):
    client = add_account(app, "alice@example.com")
    for path in ("/api/v1/placeorder", "/groww/callback", "/api/broker/credentials", "/socket.io/", "/python"):
        assert client.post(path).status_code in (400, 404)
    response = client.get("/preview/credentials")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_login_rate_limit_is_enforced(tmp_path):
    limited = create_app({
        "TESTING": True, "SECRET_KEY": "test-session-key-" * 4,
        "PREVIEW_DATABASE": str(tmp_path / "limited.db"),
        "PREVIEW_ENCRYPTION_KEY": Fernet.generate_key(),
        "RATELIMIT_ENABLED": True,
    })
    client = limited.test_client()
    responses = [send(client, "login", data={"email": "absent@example.com", "password": "wrong"}) for _ in range(6)]
    assert [r.status_code for r in responses] == [401] * 5 + [429]
