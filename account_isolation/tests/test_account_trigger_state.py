"""Durable claims tested with separate database connections; no broker calls."""
import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_flow_owner_storage import flows


@pytest.fixture
def state(flows):
    sys.modules.pop('database.account_flow_trigger_db',None)
    module=importlib.import_module('database.account_flow_trigger_db')
    a=flows.create_workflow('Alice',owner_username='alice').id
    b=flows.create_workflow('Bob',owner_username='bob').id
    return module,flows,a,b


def test_claim_and_completion_survive_new_connections(state):
    s,db,a,_=state
    token=s.create_account_trigger_arm(a,'alice')
    assert s.get_account_trigger_state(a,'alice')=='armed'
    assert s.claim_account_trigger(a,'alice',token)
    db.engine.dispose()
    assert s.get_account_trigger_state(a,'alice')=='claimed'
    assert not s.claim_account_trigger(a,'alice',token)
    assert s.consume_account_trigger(a,'alice',token)
    db.engine.dispose()
    assert s.get_account_trigger_state(a,'alice')=='consumed'
    assert s.create_account_trigger_arm(a,'alice') is None
    assert not s.claim_account_trigger(a,'alice',token)


def test_competing_claims_have_one_winner(state):
    s,_,a,_=state
    token=s.create_account_trigger_arm(a,'alice')
    # User validation uses the existing scoped user session; do that on the
    # main thread, while independent Core connections race the actual CAS.
    from unittest.mock import patch
    with patch.object(s,'_verified_workflow_owner',return_value='alice'):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:s.claim_account_trigger(a,'alice',token),range(2)))
    assert sorted(results)==[False,True]


def test_wrong_owner_and_token_cannot_mutate(state):
    s,_,a,b=state
    token=s.create_account_trigger_arm(a,'alice')
    with pytest.raises(ValueError):
        s.create_account_trigger_arm(a,'bob')
    assert s.get_account_trigger_state(a,'bob') is None
    assert not s.claim_account_trigger(a,'bob',token)
    assert not s.claim_account_trigger(a,'alice','wrong')
    assert not s.claim_account_trigger(b,'bob',token)
    assert not s.consume_account_trigger(a,'alice',token)
    assert s.get_account_trigger_state(a,'alice')=='armed'


def test_interrupted_claim_stays_closed_and_other_owner_continues(state):
    s,db,a,b=state
    token=s.create_account_trigger_arm(a,'alice')
    assert s.claim_account_trigger(a,'alice',token)
    db.engine.dispose()
    assert s.create_account_trigger_arm(a,'alice') is None
    assert not s.claim_account_trigger(a,'alice',token)
    other=s.create_account_trigger_arm(b,'bob')
    assert s.claim_account_trigger(b,'bob',other)


def test_deleted_workflow_state_cannot_be_used(state):
    s,db,a,_=state
    token=s.create_account_trigger_arm(a,'alice')
    db.delete_workflow(a,owner_username='alice')
    assert s.get_account_trigger_state(a,'alice') is None
    assert not s.claim_account_trigger(a,'alice',token)
