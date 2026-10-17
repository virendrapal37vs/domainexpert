"""All broker calls use a mock transport. No live credentials or network requests."""
import hashlib
import json

import httpx
import pytest

from tenant_preview.app import create_app
from tenant_preview.groww_probe import QUOTE_URL, TOKEN_URL, check_connection
from tenant_preview.tests.test_isolation import add_account, send


def test_documented_auth_then_quote_and_no_secret_output(monkeypatch):
    monkeypatch.setattr("tenant_preview.groww_probe.time.time", lambda: 1700000000)
    seen = []
    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            assert str(request.url) == TOKEN_URL
            assert request.method == "POST"
            assert request.headers["authorization"] == "Bearer alice-key"
            assert json.loads(request.content) == {
                "key_type": "approval", "timestamp": "1700000000",
                "checksum": hashlib.sha256(b"alice-secret1700000000").hexdigest(),
            }
            return httpx.Response(200, json={"token": "private-token", "isActive": True})
        assert request.method == "GET"
        assert str(request.url).split("?")[0] == QUOTE_URL
        assert dict(request.url.params) == {"exchange": "NSE", "segment": "CASH", "trading_symbol": "BHEL"}
        assert request.headers["authorization"] == "Bearer private-token"
        return httpx.Response(200, json={"status": "SUCCESS", "payload": {"last_price": 250}})
    result = check_connection("alice-key", "alice-secret", transport=httpx.MockTransport(handler))
    assert result["status"] == "success" and len(seen) == 2
    for secret in ("alice-key", "alice-secret", "private-token"):
        assert secret not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
def test_auth_errors_do_not_attempt_quote_or_echo_raw_body(status):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"message": "secret-api-key private-token"},
                              headers={"Location": "https://untrusted.example"})
    result = check_connection("secret-api-key", "secret", transport=httpx.MockTransport(handler))
    assert len(seen) == 1
    assert result["stage"] == "authentication" and result["http_status"] == status
    assert "secret-api-key" not in json.dumps(result) and "private-token" not in json.dumps(result)
    if status == 403:
        assert result["reason"] == "forbidden"


@pytest.mark.parametrize("body", [[], {}, {"token": 12}, {"token": "token", "isActive": False}])
def test_invalid_or_inactive_tokens_are_not_used(body):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=body)
    result = check_connection("key", "secret", transport=httpx.MockTransport(handler))
    assert result["status"] == "error" and len(seen) == 1


def test_auth_success_quote_403_is_reported_as_quote_failure():
    seen = []
    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(200, json={"token": "temporary-token"})
        return httpx.Response(403, json={"error": {"message": "temporary-token secret"}})
    result = check_connection("key", "secret", transport=httpx.MockTransport(handler))
    assert result["stage"] == "quote" and result["reason"] == "forbidden"
    assert len(seen) == 2 and "temporary-token" not in json.dumps(result)


def test_timeout_and_non_json_responses_do_not_leak_secrets():
    def timeout(request):
        raise httpx.ReadTimeout("private-key included in exception", request=request)
    result = check_connection("private-key", "secret", transport=httpx.MockTransport(timeout))
    assert result["reason"] == "network" and "private-key" not in json.dumps(result)
    result = check_connection("key", "secret", transport=httpx.MockTransport(lambda r: httpx.Response(200, text="private-body")))
    assert result["reason"] == "invalid_response" and "private-body" not in json.dumps(result)


def test_endpoint_uses_only_session_owner_and_never_environment_key(app, monkeypatch):
    alice = add_account(app, "alice@example.com")
    bob = add_account(app, "bob@example.com")
    send(alice, "credentials", "PUT", {"api_key": "alice-key", "api_secret": "alice-secret"})
    send(bob, "credentials", "PUT", {"api_key": "bob-key", "api_secret": "bob-secret"})
    monkeypatch.setenv("BROKER_API_KEY", "production-key")
    monkeypatch.setenv("BROKER_API_SECRET", "production-secret")
    calls = []
    def probe(key, secret):
        calls.append((key, secret))
        return {"status": "success", "message": "Mock connection checked"}
    monkeypatch.setattr("tenant_preview.groww_probe.check_connection", probe)
    app.config["ALLOW_GROWW_CHECK"] = True
    assert send(alice, "groww/check", data={"user_id": 2, "email": "bob@example.com"}).status_code == 200
    assert send(bob, "groww/check", data={"user_id": 1}).status_code == 200
    assert calls == [("alice-key", "alice-secret"), ("bob-key", "bob-secret")]
    send(alice, "credentials", "DELETE")
    assert send(alice, "groww/check").status_code == 400
    assert len(calls) == 2


def test_disabled_unauthenticated_demo_and_csrf_gates_do_not_call_groww(app, monkeypatch):
    calls = []
    monkeypatch.setattr("tenant_preview.groww_probe.check_connection", lambda *a: calls.append(a))
    assert send(app.test_client(), "groww/check").status_code == 401
    client = add_account(app, "alice@example.com")
    send(client, "credentials", "PUT", {"api_key": "demo-key", "api_secret": "demo-secret"})
    assert send(client, "groww/check").status_code == 403
    app.config["ALLOW_GROWW_CHECK"] = True
    assert send(client, "groww/check").status_code == 400
    assert client.post("/preview/groww/check").status_code == 400
    assert calls == []


def test_probe_rate_limit(app, monkeypatch):
    # Limiter is configured at app creation, so use a fresh app with limits enabled.
    limited = create_app({**app.config, "RATELIMIT_ENABLED": True, "ALLOW_GROWW_CHECK": True})
    client = add_account(limited, "alice@example.com")
    send(client, "credentials", "PUT", {"api_key": "alice-key", "api_secret": "alice-secret"})
    calls = []
    def probe(*args):
        calls.append(args)
        return {"status": "success", "message": "checked"}
    monkeypatch.setattr("tenant_preview.groww_probe.check_connection", probe)
    assert [send(client, "groww/check").status_code for _ in range(3)] == [200, 200, 429]
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [{}, {"last_price": None}, {"last_price": True}])
def test_success_without_usable_quote_is_not_connection_success(payload):
    seen = []
    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(200, json={"token": "token"})
        return httpx.Response(200, json={"status": "SUCCESS", "payload": payload})
    result = check_connection("key", "secret", transport=httpx.MockTransport(handler))
    assert result["stage"] == "quote" and result["reason"] == "invalid_response"
