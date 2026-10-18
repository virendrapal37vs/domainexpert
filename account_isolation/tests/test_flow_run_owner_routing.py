"""Actual run boundary and HTTP request guard bodies; no execution enabled."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from flask import Flask, jsonify
import pytest
from test_strategy_account_guard import function

FILE='blueprints/flow.py'


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','true')
    validate=Mock(return_value='alice')
    monkeypatch.setitem(sys.modules,'utils.flow_execution_owner',SimpleNamespace(validate_flow_execution_owner=validate))
    env={}
    env['_account_flow_run_error']=function(FILE,'_account_flow_run_error',env)
    run=function(FILE,'_run_or_start',env)
    return env,validate,run


def test_run_passes_exact_id_and_key_then_remains_disabled(boundary):
    env,validate,run=boundary
    assert run(SimpleNamespace(id=42),api_key='fake-key')['code']=='FLOW_ACCOUNT_ISOLATION_PENDING'
    validate.assert_called_once_with(42,'fake-key')


def test_invalid_owner_stops_before_executor_import(boundary):
    env,validate,run=boundary
    validate.side_effect=ValueError('synthetic sensitive error')
    result=run(SimpleNamespace(id=42),api_key='other-key')
    assert result['code']=='FLOW_OWNER_AUTH_FAILED'
    assert 'sensitive' not in str(result)


def test_cross_account_activation_request_rejected_before_key_lookup(boundary,monkeypatch):
    env,validate,run=boundary
    env.update(jsonify=jsonify,_flow_account_owner=lambda:'alice',get_current_api_key=Mock())
    monkeypatch.setitem(sys.modules,'database.flow_db',SimpleNamespace(get_account_workflow=lambda wid,owner:None))
    fn=function(FILE,'_account_flow_request_block',env)
    with Flask(__name__).app_context():
        assert fn(2)[1]==404
    env['get_current_api_key'].assert_not_called()
    validate.assert_not_called()


@pytest.mark.parametrize('name',['activate_workflow','execute_workflow_now'])
def test_http_entry_checks_request_guard_before_shared_imports(name):
    block=Mock(return_value=({'error':'blocked'},503))
    fn=function(FILE,name,{'_account_flow_request_block':block})
    assert fn(42)[1]==503
    block.assert_called_once_with(42)


def test_legacy_boundary_returns_without_validator(boundary,monkeypatch):
    env,validate,run=boundary
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','false')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES','false')
    assert env['_account_flow_run_error'](SimpleNamespace(id=42),'fake-key') is None
    validate.assert_not_called()


@pytest.mark.parametrize('secret,expected',[(None,401),('synthetic-secret',500)])
def test_account_webhook_never_borrows_session_or_environment_key(boundary,monkeypatch,secret,expected):
    workflow=SimpleNamespace(id=1,webhook_enabled=True,is_active=True,
        webhook_secret=secret,webhook_auth_type='payload')
    monkeypatch.setitem(sys.modules,'database.flow_db',SimpleNamespace(
        get_workflow_by_webhook_token=lambda token:workflow,get_workflow_api_key=lambda wf:None))
    fallback=Mock(side_effect=AssertionError('No session fallback allowed'))
    fn=function(FILE,'_execute_webhook',{'jsonify':jsonify,'get_current_api_key':fallback,'logger':Mock()})
    with Flask(__name__).app_context():
        response,status=fn('synthetic-token',webhook_data={'secret':'synthetic-secret'})
    assert status==expected
    fallback.assert_not_called()
