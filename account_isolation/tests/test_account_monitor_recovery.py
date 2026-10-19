"""Rebuild registration from persisted workflows, without starting monitor threads."""
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_account_flow_execution import runnable
from test_account_flow_monitor_integration import monitors


@pytest.mark.parametrize('kind',['priceAlert','orderUpdateTrigger'])
@pytest.mark.parametrize('case',['valid','revoked','policy_off','once'])
def test_account_recovery_admission(monitors,monkeypatch,kind,case):
    m=monitors;s=m.s
    m.arm(kind)
    if case=='revoked':
        s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
        s.auth.db_session.commit()
    elif case=='policy_off':
        monkeypatch.setenv('DOMAINXPERT_ACCOUNT_FLOW_EXECUTION','false')
    elif case=='once':
        row=s.db.get_workflow(s.a)
        nodes=[{**row.nodes[0],'data':{**row.nodes[0]['data'],'trigger':'once'}},row.nodes[1]]
        s.db.update_workflow(s.a,nodes=nodes)
    module=m.price if kind=='priceAlert' else m.order
    monitor=module.flow_price_monitor if kind=='priceAlert' else module.flow_order_update_monitor
    method='add_alert' if kind=='priceAlert' else 'add_watch'
    calls=Mock(return_value=True)
    monkeypatch.setattr(monitor,method,calls)
    restore=module.restore_price_alerts if kind=='priceAlert' else module.restore_order_update_watches
    count=restore()
    expected=2 if case=='valid' else 0 if case=='policy_off' else 1
    assert count==expected
    assert calls.call_count==expected
    by_id={call.kwargs['workflow_id']:call.kwargs for call in calls.call_args_list}
    if s.a in by_id:
        assert by_id[s.a]['api_key']=='a-key'
        if kind=='orderUpdateTrigger':
            assert by_id[s.a]['user_id']=='alice'
    if s.b in by_id:
        assert by_id[s.b]['api_key']=='b-key'
        if kind=='orderUpdateTrigger':
            assert by_id[s.b]['user_id']=='bob'
    s.clients['a-key'].place_order.assert_not_called()
    s.clients['b-key'].place_order.assert_not_called()
