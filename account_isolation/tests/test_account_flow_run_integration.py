"""HTTP Run Now / scheduler -> guarded engine with real DB/auth, fake broker."""
from flask import Flask,jsonify
from flask_wtf.csrf import CSRFProtect,generate_csrf
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_account_flow_execution import runnable
from test_strategy_account_guard import function


@pytest.fixture
def http(runnable):
    s=runnable
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='synthetic-run-only')
    CSRFProtect(app)
    @app.get('/csrf')
    def csrf():
        return {'token':generate_csrf()}
    env={'jsonify':jsonify,'get_current_api_key':lambda:'a-key','logger':Mock()}
    for name in ['_flow_account_owner','_account_flow_run_error','_account_flow_request_block',
                 '_execution_blocked','_execution_status_code','_run_or_start']:
        env[name]=function('blueprints/flow.py',name,env)
    app.add_url_rule('/run/<int:workflow_id>',view_func=function('blueprints/flow.py','execute_workflow_now',env),methods=['POST'])
    client=app.test_client()
    with client.session_transaction() as session:
        session['user']='alice'
    return s,client,{'X-CSRFToken':client.get('/csrf').json['token']}


def test_run_now_route_reaches_actual_account_engine_with_own_key(http):
    s,client,headers=http
    result=client.post(f'/run/{s.a}',json={'user':'bob','api_key':'b-key'},headers=headers)
    assert result.status_code==200 and result.json['status']=='success'
    s.clients['a-key'].place_order.assert_called_once()
    s.clients['b-key'].place_order.assert_not_called()
    assert s.db.get_execution(result.json['execution_id']).workflow_id==s.a


def test_run_now_other_owner_is_404_before_engine(http):
    s,client,headers=http
    assert client.post(f'/run/{s.b}',headers=headers).status_code==404
    s.factory.assert_not_called()


def test_disabled_or_staging_http_execution_is_503(http,monkeypatch):
    s,client,headers=http
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE','true')
    assert client.post(f'/run/{s.a}',headers=headers).status_code==503
    s.factory.assert_not_called()


def test_schedule_uses_only_stored_owner_key_through_guarded_engine(runnable):
    s=runnable
    s.db.activate_workflow(s.a,api_key='a-key',owner_username='alice')
    fn=function('services/flow_scheduler_service.py','execute_workflow_scheduled',{
        'logger':Mock(),'get_market_hours_config':lambda wf:{'enabled':False}})
    fn(s.a)  # no plaintext key in scheduled callback arguments
    assert s.db.get_workflow_executions(s.a)[0].status=='completed'
    s.clients['a-key'].place_order.assert_called_once()
    s.clients['b-key'].place_order.assert_not_called()


def test_revoked_schedule_cannot_submit_a_run(runnable):
    s=runnable
    s.db.activate_workflow(s.a,api_key='a-key',owner_username='alice')
    s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
    s.auth.db_session.commit()
    fn=function('services/flow_scheduler_service.py','execute_workflow_scheduled',{})
    fn(s.a)
    s.factory.assert_not_called()
    assert s.db.get_workflow_executions(s.a)==[]


def test_inactive_schedule_cannot_submit_a_run(runnable):
    s=runnable
    fn=function('services/flow_scheduler_service.py','execute_workflow_scheduled',{})
    fn(s.a,api_key='a-key')
    s.factory.assert_not_called()
    assert s.db.get_workflow_executions(s.a)==[]
