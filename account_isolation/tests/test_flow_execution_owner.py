"""Fresh SQLite credential checks and execution bypass guards; no broker calls."""
import importlib
import sys
import pytest
from test_flow_owner_storage import flows
from test_strategy_account_guard import function


@pytest.fixture
def owned(flows):
    auth=importlib.import_module('database.auth_db')
    auth.Base.metadata.create_all(auth.engine)
    for owner,key in [('alice','a-key'),('bob','b-key')]:
        auth.db_session.add(auth.Auth(name=owner,broker='groww',auth=auth.encrypt_token(owner+'-token'),is_revoked=False))
        auth.db_session.add(auth.ApiKeys(user_id=owner,api_key_hash=auth.ph.hash(key+auth.PEPPER),api_key_encrypted='unused'))
    auth.db_session.commit()
    a=flows.create_workflow('Alice',owner_username='alice')
    b=flows.create_workflow('Bob',owner_username='bob')
    from utils.flow_execution_owner import validate_flow_execution_owner
    return flows,auth,a.id,b.id,validate_flow_execution_owner


def test_exact_key_matches_workflow_owner(owned):
    _,_,a,b,validate=owned
    assert validate(a,'a-key') == 'alice'
    assert validate(b,'b-key') == 'bob'
    with pytest.raises(ValueError):
        validate(a,'b-key')


@pytest.mark.parametrize('key',[None,'','invalid-key'])
def test_missing_or_invalid_key_rejected(owned,key):
    _,_,a,_,validate=owned
    with pytest.raises(ValueError):
        validate(a,key)


def test_revocation_and_rotation_read_fresh_database(owned):
    _,auth,a,b,validate=owned
    assert validate(a,'a-key') == 'alice'
    auth.ApiKeys.query.filter_by(user_id='alice').update({'api_key_hash':auth.ph.hash('new-key'+auth.PEPPER)})
    auth.db_session.commit()
    with pytest.raises(ValueError):
        validate(a,'a-key')
    assert validate(a,'new-key') == 'alice'
    auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
    auth.db_session.commit()
    with pytest.raises(ValueError):
        validate(a,'new-key')
    assert validate(b,'b-key') == 'bob'


def test_legacy_ownerless_workflow_cannot_borrow_key(owned):
    db,_,a,_,validate=owned
    db.FlowWorkflow.query.filter_by(id=a).update({'owner_username':None})
    db.db_session.commit()
    with pytest.raises(ValueError):
        validate(a,'a-key')


@pytest.mark.parametrize('name',['start_workflow_in_background','_execute_workflow_locked'])
def test_internal_execution_entry_points_refuse_before_side_effects(name,monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','true')
    fn=function('services/flow_executor_service.py',name,{})
    assert fn(1,api_key='synthetic-key')['code'] == 'FLOW_ACCOUNT_ISOLATION_PENDING'
