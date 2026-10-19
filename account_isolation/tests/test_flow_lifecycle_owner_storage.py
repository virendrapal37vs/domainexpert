"""Real lifecycle database writes and fresh auth validation; no trigger starts."""
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned


def test_verified_activation_stores_only_owner_key_encrypted(owned):
    db,_,a,b,_=owned
    result=db.activate_workflow(a,api_key='a-key',owner_username='alice')
    assert result.is_active is True
    assert result.owner_username=='alice'
    assert result.api_key!='a-key'
    assert db.get_workflow_api_key(result)=='a-key'
    assert db.get_workflow(b).is_active is False
    assert db.get_workflow(b).api_key is None


@pytest.mark.parametrize('owner,key',[('alice','b-key'),('bob','b-key'),(None,'a-key'),('alice',None)])
def test_wrong_or_missing_activation_identity_causes_no_write(owned,owner,key):
    db,_,a,b,_=owned
    with pytest.raises(ValueError):
        db.activate_workflow(a,api_key=key,owner_username=owner)
    assert db.get_workflow(a).is_active is False
    assert db.get_workflow(a).api_key is None
    assert db.get_workflow(b).is_active is False


def test_revoked_owner_cannot_activate_but_can_deactivate(owned):
    db,auth,a,b,_=owned
    db.activate_workflow(a,api_key='a-key',owner_username='alice')
    auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
    auth.db_session.commit()
    assert db.deactivate_workflow(a,owner_username='alice').is_active is False
    with pytest.raises(ValueError):
        db.activate_workflow(a,api_key='a-key',owner_username='alice')
    assert db.get_workflow(a).is_active is False
    assert db.get_workflow(b).is_active is False


def test_wrong_owner_cannot_deactivate_another_workflow(owned):
    db,_,a,b,_=owned
    db.activate_workflow(b,api_key='b-key',owner_username='bob')
    with pytest.raises(ValueError):
        db.deactivate_workflow(b,owner_username='alice')
    assert db.get_workflow(b).is_active is True


def test_rotated_key_cannot_be_persisted_as_active_key(owned):
    db,auth,a,_,_=owned
    auth.ApiKeys.query.filter_by(user_id='alice').update({'api_key_hash':auth.ph.hash('new-key'+auth.PEPPER)})
    auth.db_session.commit()
    with pytest.raises(ValueError):
        db.activate_workflow(a,api_key='a-key',owner_username='alice')
    assert db.get_workflow(a).api_key is None
    db.activate_workflow(a,api_key='new-key',owner_username='alice')
    assert db.get_workflow_api_key(db.get_workflow(a))=='new-key'
