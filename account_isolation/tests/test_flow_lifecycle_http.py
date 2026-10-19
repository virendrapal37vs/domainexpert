"""Real route bodies -> lifecycle service -> SQLite/auth; trigger transports mocked."""
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from flask import Flask,jsonify
from flask_wtf.csrf import CSRFProtect,generate_csrf
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_flow_engine_offline_integration import NODES,EDGES
from test_strategy_account_guard import function


@pytest.fixture
def http(owned,monkeypatch):
    db,auth,a,b,_=owned
    for wid in (a,b):
        db.update_workflow(wid,nodes=NODES,edges=EDGES)
    lock=threading.Lock()
    release=Mock()
    pending=Mock(return_value=False)
    monkeypatch.setitem(sys.modules,'services.flow_executor_service',SimpleNamespace(
        get_workflow_lock=lambda wid:lock,release_workflow_subscriptions=release,
        has_workflow_subscriptions=pending))
    import services.account_flow_activation as service
    cleanup,register=Mock(),Mock()
    monkeypatch.setattr(service,'remove_account_triggers',cleanup)
    monkeypatch.setattr(service,'register_account_trigger',register)
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='synthetic-lifecycle-only')
    CSRFProtect(app)
    @app.get('/csrf')
    def csrf():
        return {'token':generate_csrf()}
    key=Mock(return_value='a-key')
    env={'jsonify':jsonify,'get_current_api_key':key}
    env['_flow_account_owner']=function('blueprints/flow.py','_flow_account_owner',{})
    for action in ('activate','deactivate'):
        name=action+'_workflow'
        app.add_url_rule('/flows/<int:workflow_id>/'+action,endpoint=action,
            view_func=function('blueprints/flow.py',name,env),methods=['POST'])
    client=app.test_client()
    with client.session_transaction() as session:
        session['user']='alice'
    headers={'X-CSRFToken':client.get('/csrf').json['token']}
    return SimpleNamespace(client=client,headers=headers,db=db,auth=auth,a=a,b=b,
        cleanup=cleanup,register=register,key=key,pending=pending,release=release,lock=lock)


def test_activation_routes_session_owner_and_key_to_service(http):
    s=http
    response=s.client.post(f'/flows/{s.a}/activate',json={'owner_username':'bob'},headers=s.headers)
    assert response.status_code==200
    assert s.db.get_workflow(s.a).is_active
    assert not s.db.get_workflow(s.b).is_active
    args=s.register.call_args.args
    assert args[2:] == ('alice','a-key')


def test_other_workflow_cannot_activate_or_deactivate(http):
    s=http
    for action in ('activate','deactivate'):
        response=s.client.post(f'/flows/{s.b}/{action}',headers=s.headers)
        assert response.status_code==404
    s.register.assert_not_called()
    s.cleanup.assert_not_called()


def test_registration_failure_returns_inactive_and_retryable(http):
    s=http
    s.register.side_effect=RuntimeError('synthetic internal failure')
    response=s.client.post(f'/flows/{s.a}/activate',headers=s.headers)
    assert response.status_code==503
    assert not s.db.get_workflow(s.a).is_active
    assert not s.lock.locked()


def test_revoked_broker_key_does_not_prevent_owner_stop(http):
    s=http
    assert s.client.post(f'/flows/{s.a}/activate',headers=s.headers).status_code==200
    s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
    s.auth.db_session.commit()
    s.key.side_effect=AssertionError('Stopping must not fetch an API key')
    response=s.client.post(f'/flows/{s.a}/deactivate',headers=s.headers)
    assert response.status_code==200
    assert not s.db.get_workflow(s.a).is_active
    s.release.assert_called_once_with(s.a,owner_username='alice')


def test_pending_cleanup_leaves_inactive_row_for_retry(http):
    s=http
    assert s.client.post(f'/flows/{s.a}/activate',headers=s.headers).status_code==200
    s.pending.return_value=True
    response=s.client.post(f'/flows/{s.a}/deactivate',headers=s.headers)
    assert response.status_code==503 and response.json['cleanup_pending'] is True
    assert not s.db.get_workflow(s.a).is_active
    s.pending.return_value=False
    assert s.client.post(f'/flows/{s.a}/deactivate',headers=s.headers).status_code==200


def test_missing_csrf_and_anonymous_are_rejected(http):
    s=http
    assert s.client.post(f'/flows/{s.a}/activate').status_code==400
    with s.client.session_transaction() as session:
        session.pop('user')
    assert s.client.post(f'/flows/{s.a}/activate',headers=s.headers).status_code==401
    s.register.assert_not_called()
