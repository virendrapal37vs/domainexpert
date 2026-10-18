"""Real route bodies and SQLite, bypassing the outer feature guard for tests only."""
import sys
from types import SimpleNamespace
from flask import Flask, jsonify, request
from flask_wtf.csrf import CSRFProtect, generate_csrf
import pytest
from test_strategy_account_guard import function
from test_flow_owner_storage import flows


@pytest.fixture
def http(flows, monkeypatch):
    monkeypatch.setitem(sys.modules, 'services.flow_workflow_validator',
        SimpleNamespace(validate_workflow=lambda *a, **k: [], trigger_config=lambda nodes: {}))
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='synthetic-tests-only')
    CSRFProtect(app)
    @app.get('/csrf')
    def csrf():
        return {'token': generate_csrf()}
    env = {'jsonify': jsonify, 'request': request, 'logger': SimpleNamespace(warning=lambda *a: None)}
    env['_flow_account_owner'] = function('blueprints/flow.py', '_flow_account_owner', {})
    env['_existing_for_trigger_check'] = function('blueprints/flow.py', '_existing_for_trigger_check', {})
    for name, path, verb in [('list_workflows','/flows','GET'),('create_workflow','/flows','POST'),
        ('get_workflow','/flows/<int:workflow_id>','GET'),('update_workflow','/flows/<int:workflow_id>','PUT'),
        ('delete_workflow','/flows/<int:workflow_id>','DELETE')]:
        app.add_url_rule(path, endpoint=name, view_func=function('blueprints/flow.py', name, env), methods=[verb])
    client = app.test_client()
    with client.session_transaction() as session:
        session['user'] = 'alice'
    token = client.get('/csrf').json['token']
    return client, {'X-CSRFToken': token}, flows


def test_create_ignores_claimed_owner_and_list_detail_hide_other_account(http):
    client, headers, db = http
    bob = db.create_workflow('Bob', owner_username='bob')
    response = client.post('/flows', json={'name': 'Alice', 'owner_username': 'bob', 'is_active': True}, headers=headers)
    assert response.status_code == 201
    own = db.get_workflow(response.json['id'])
    assert own.owner_username == 'alice'
    assert own.is_active is False
    assert [w['id'] for w in client.get('/flows').json] == [own.id]
    assert client.get(f'/flows/{bob.id}').status_code == 404
    assert client.get(f'/flows/{own.id}').status_code == 200


def test_update_cannot_change_other_account_or_transfer_ownership(http):
    client, headers, db = http
    bob = db.create_workflow('Bob', owner_username='bob')
    alice = db.create_workflow('Alice', owner_username='alice')
    assert client.put(f'/flows/{bob.id}', json={'name':'stolen'}, headers=headers).status_code == 404
    response = client.put(f'/flows/{alice.id}', json={'name':'Renamed', 'owner_username':'bob'}, headers=headers)
    assert response.status_code == 200
    assert db.get_account_workflow(alice.id,'alice').name == 'Renamed'
    assert db.get_workflow(bob.id).name == 'Bob'


def test_delete_rejects_other_owner_and_keeps_own_teardown_guarded(http):
    client, headers, db = http
    a = db.create_workflow('Alice', owner_username='alice')
    b = db.create_workflow('Bob', owner_username='bob')
    assert client.delete(f'/flows/{b.id}', headers=headers).status_code == 404
    assert client.delete(f'/flows/{a.id}', headers=headers).status_code == 503
    assert db.get_workflow(a.id) and db.get_workflow(b.id)


def test_anonymous_and_missing_csrf_cannot_write(http):
    client, headers, db = http
    assert client.post('/flows',json={'name':'no csrf'}).status_code == 400
    with client.session_transaction() as session:
        session.pop('user')
    assert client.get('/flows').status_code == 401
    assert client.post('/flows',json={'name':'anon'},headers=headers).status_code == 401
    assert db.get_all_workflows() == []


def test_database_scoped_update_and_delete_cannot_mutate_other_account(http):
    _, _, db = http
    b = db.create_workflow('Bob', owner_username='bob')
    assert db.update_workflow(b.id, owner_username='alice', name='stolen') is None
    assert db.delete_workflow(b.id, owner_username='alice') is False
    assert db.get_workflow(b.id).name == 'Bob'
