import importlib
from pathlib import Path
from sqlalchemy import select


def login(client, username, logged_in=False):
    with client.session_transaction() as session:
        session["user"] = username
        session["logged_in"] = logged_in


def put(client, data, csrf=True):
    token = client.get("/csrf").json["csrf_token"]
    return client.put("/api/account/brokers/groww", json=data,
                      headers={"X-CSRFToken": token} if csrf else {})


def test_separate_owners_and_ciphertext(main_app, monkeypatch):
    alice, bob = main_app.test_client(), main_app.test_client()
    login(alice, "alice"); login(bob, "bob")
    monkeypatch.setenv("BROKER_API_KEY", "production-key")
    assert put(alice, {"api_key": "alice-key", "api_secret": "alice-secret", "username": "bob"}).status_code == 200
    assert bob.get("/api/account/brokers/groww").json["configured"] is False
    assert put(bob, {"api_key": "bob-key", "api_secret": "bob-secret"}).status_code == 200
    db = importlib.import_module("database.account_broker_db")
    assert db.get_groww_credentials("alice") == ("alice-key", "alice-secret")
    assert db.get_groww_credentials("bob") == ("bob-key", "bob-secret")
    assert db.get_groww_credentials("missing") is None
    rows = db.db_session.scalars(select(db.AccountBrokerCredential)).all()
    assert all("alice-key" not in row.encrypted_key and "alice-secret" not in row.encrypted_secret for row in rows)
    response = alice.get("/api/account/brokers/groww")
    assert response.headers["Cache-Control"] == "no-store"
    assert "alice-key" not in response.text and "alice-secret" not in response.text


def test_auth_csrf_unknown_user_and_live_rotation(main_app):
    client = main_app.test_client()
    assert client.get("/api/account/brokers/groww").status_code == 401
    login(client, "missing")
    assert client.get("/api/account/brokers/groww").status_code == 401
    login(client, "alice")
    data = {"api_key": "key", "api_secret": "secret"}
    assert put(client, data, csrf=False).status_code == 400
    assert put(client, {"api_key": [], "api_secret": "secret"}).status_code == 400
    assert put(client, data).status_code == 200
    login(client, "alice", logged_in=True)
    assert put(client, data).status_code == 409


def test_feature_disabled(main_app, monkeypatch):
    monkeypatch.setenv("DOMAINXPERT_PER_USER_GROWW", "false")
    client = main_app.test_client(); login(client, "alice")
    assert client.get("/api/account/brokers/groww").status_code == 404
    assert put(client, {"api_key": "key", "api_secret": "secret"}).status_code == 404


def test_admin_authorization_is_from_database(main_app):
    client = main_app.test_client()
    assert client.get("/instance-setting").status_code == 401
    login(client, "bob")
    with client.session_transaction() as session:
        session["is_admin"] = True
    assert client.get("/instance-setting").status_code == 403
    login(client, "alice")
    assert client.get("/instance-setting").status_code == 200


def test_settings_blueprints_have_role_hook():
    root = Path(__file__).resolve().parents[2]
    for name, bp in [("admin", "admin_bp"), ("broker_credentials", "broker_credentials_bp"), ("system_permissions", "system_permissions_bp")]:
        source = (root / "blueprints" / f"{name}.py").read_text()
        assert f"{bp}.before_request(require_instance_admin)" in source


def load_function(relative_path, function_name, namespace):
    """Exercise the real function body without booting unrelated broker services."""
    import ast
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / relative_path).read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function_name)
    function.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(root / relative_path), "exec"), namespace)
    return namespace[function_name]


def test_groww_auth_requires_explicit_credentials_in_scoped_mode(main_app, monkeypatch):
    import os
    calls = []
    authenticate = load_function("broker/groww/api/auth_api.py", "authenticate_broker", {
        "os": os, "get_access_token_via_checksum": lambda *args: calls.append(args) or ("token", None),
    })
    monkeypatch.setenv("BROKER_API_KEY", "global-key")
    monkeypatch.setenv("BROKER_API_SECRET", "global-secret")
    assert authenticate("groww")[0] is None
    assert calls == []
    assert authenticate("groww", credentials=("alice-key", "alice-secret")) == ("token", None)
    assert calls == [("alice-key", "alice-secret")]
    monkeypatch.setenv("DOMAINXPERT_PER_USER_GROWW", "false")
    assert authenticate("groww") == ("token", None)
    assert calls[-1] == ("global-key", "global-secret")


def test_callback_selects_current_owner_not_request_owner(main_app):
    import logging
    from flask import session, request, jsonify
    db = importlib.import_module("database.account_broker_db")
    db.save_groww_credentials("alice", "alice-key", "alice-secret")
    db.save_groww_credentials("bob", "bob-key", "bob-secret")
    calls = []
    def auth(code, **kwargs):
        calls.append(kwargs["credentials"])
        return "fake-token", None
    main_app.broker_auth_functions = {"groww_auth": auth}
    callback = load_function("blueprints/brlogin.py", "broker_callback", {
        "app": main_app, "session": session, "request": request, "jsonify": jsonify,
        "logger": logging.getLogger("test-callback"),
        "handle_auth_success": lambda token, username, broker, **kwargs: (username, broker),
    })
    with main_app.test_request_context("/groww/callback?username=bob"):
        session["user"] = "alice"
        assert callback("groww") == ("alice", "groww")
    with main_app.test_request_context("/groww/callback?username=alice"):
        session["user"] = "bob"
        assert callback("groww") == ("bob", "groww")
    assert calls == [("alice-key", "alice-secret"), ("bob-key", "bob-secret")]


def test_scoped_broker_config_does_not_return_global_key(main_app, monkeypatch):
    import os
    from flask import session, jsonify
    monkeypatch.setenv("BROKER_API_KEY", "production-key-do-not-return")
    config = load_function("blueprints/auth.py", "get_broker_config", {
        "os": os, "session": session, "jsonify": jsonify,
    })
    with main_app.test_request_context("/auth/broker-config"):
        session["user"] = "alice"
        result = config()
        assert result.json["per_user_credentials"] is True
        assert result.json["broker_api_key"] == ""
        assert "production-key" not in result.get_data(as_text=True)
    with main_app.test_request_context("/auth/broker-config"):
        assert config()[1] == 401
