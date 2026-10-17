import importlib
import sys
import pytest

@pytest.fixture
def client(main_app, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PUBLIC_SIGNUP', 'true')
    sys.modules.pop('blueprints.account_signup', None)
    main_app.register_blueprint(importlib.import_module('blueprints.account_signup').signup_bp)
    return main_app.test_client()

def post(client, **changes):
    data = dict(username='newuser', email='new@example.com', password='StrongPass123!', confirm_password='StrongPass123!')
    data.update(changes)
    csrf = client.get('/csrf').json['csrf_token']
    return client.post('/auth/signup', json=data, headers={'X-CSRFToken': csrf})

def test_signup_normal_role_and_no_session(client):
    assert post(client, is_admin=True, role='admin').status_code == 201
    from database.user_db import find_user_by_exact_username
    assert not find_user_by_exact_username('newuser').is_admin
    with client.session_transaction() as session:
        assert not session.get('user') and not session.get('logged_in')

def test_duplicate(client):
    assert post(client).status_code == 201
    assert post(client).status_code == 409

@pytest.mark.parametrize('changes', [dict(username='../bad'), dict(email='bad'), dict(password='weak'), dict(confirm_password='different'), dict(username=12)])
def test_invalid(client, changes):
    assert post(client, **changes).status_code == 400

def test_csrf(client):
    assert client.post('/auth/signup', json={}).status_code == 400

def test_disabled(client, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PUBLIC_SIGNUP', 'false')
    assert post(client).status_code == 403
