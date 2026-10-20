"""Actual monitor pool and guarded graph; synthetic broker, durable SQLite claim."""
import importlib
import sys
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_account_flow_execution import runnable
from test_account_flow_monitor_integration import monitors,event
from test_account_flow_activation import activation


@pytest.fixture
def claims(monitors):
    sys.modules.pop('database.account_flow_trigger_db',None)
    state=importlib.import_module('database.account_flow_trigger_db')
    m=monitors
    def arm(kind):
        m.arm(kind)
        for wid,owner in [(m.s.a,'alice'),(m.s.b,'bob')]:
            row=m.s.db.get_workflow(wid)
            nodes=[{**row.nodes[0],'data':{**row.nodes[0]['data'],'trigger':'once'}},row.nodes[1]]
            m.s.db.update_workflow(wid,nodes=nodes)
            state.create_account_trigger_arm(wid,owner)
        monitor=m.price.flow_price_monitor if kind=='priceAlert' else m.order.flow_order_update_monitor
        entries=monitor._alerts if kind=='priceAlert' else monitor._watches
        for entry in entries.values():
            entry.trigger='once'
    return m,state,arm


@pytest.mark.parametrize('kind',['priceAlert','orderUpdateTrigger'])
def test_actual_pool_consumes_only_owner_and_cannot_replay(claims,kind):
    m,state,arm=claims;s=m.s
    arm(kind)
    if kind=='priceAlert':
        m.price.flow_price_monitor._check_alert(m.price.flow_price_monitor._alerts[s.a])
        m.drain(m.price)
        assert s.a not in m.price.flow_price_monitor._alerts
    else:
        m.order.flow_order_update_monitor._on_order_update(event('alice'))
        m.drain(m.order)
        assert s.a not in m.order.flow_order_update_monitor._watches
    assert state.get_account_trigger_state(s.a,'alice')=='consumed'
    assert not s.db.get_workflow(s.a).is_active
    assert state.get_account_trigger_state(s.b,'bob')=='armed'
    assert s.db.get_workflow(s.b).is_active
    s.clients['a-key'].place_order.assert_called_once()
    s.clients['b-key'].place_order.assert_not_called()
    s.db.engine.dispose()
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_TRIGGER_NOT_ARMED'
    assert s.clients['a-key'].place_order.call_count==1


def test_crash_after_claim_is_not_retried_or_restored(claims,monkeypatch):
    m,state,arm=claims;s=m.s
    arm('priceAlert')
    original=s.engine._execute_workflow_graph
    monkeypatch.setattr(s.engine,'_execute_workflow_graph',Mock(side_effect=RuntimeError('simulated interruption')))
    with pytest.raises(RuntimeError):
        s.engine.execute_workflow(s.a,webhook_data={'trigger_type':'price_alert','trigger_price':150},api_key='a-key')
    assert state.get_account_trigger_state(s.a,'alice')=='claimed'
    monkeypatch.setattr(s.engine,'_execute_workflow_graph',original)
    s.db.engine.dispose()
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_TRIGGER_NOT_ARMED'
    from utils.flow_execution_owner import account_monitor_restore_owner
    with pytest.raises(ValueError):
        account_monitor_restore_owner(s.a,'a-key',{'trigger':'once'})
    s.clients['a-key'].place_order.assert_not_called()
    assert s.engine.execute_workflow(s.b,webhook_data={'trigger_type':'price_alert','trigger_price':150},api_key='b-key')['status']=='success'


def test_revoked_key_does_not_spend_arm(claims):
    m,state,arm=claims;s=m.s
    arm('priceAlert')
    s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True});s.auth.db_session.commit()
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_OWNER_AUTH_FAILED'
    assert state.get_account_trigger_state(s.a,'alice')=='armed'
    s.clients['a-key'].place_order.assert_not_called()


def test_activation_creates_arm_and_refuses_consumed_reactivation(activation):
    s=activation
    sys.modules.pop('database.account_flow_trigger_db',None)
    state=importlib.import_module('database.account_flow_trigger_db')
    row=s.db.get_workflow(s.a)
    nodes=[{**row.nodes[0],'type':'priceAlert','data':{'symbol':'BHEL','exchange':'NSE','price':100,'condition':'greater_than','trigger':'once'}},row.nodes[1]]
    s.db.update_workflow(s.a,nodes=nodes)
    assert s.module.activate_account_workflow(s.a,'alice','a-key')[1]==200
    token=state.get_account_trigger_arm(s.a,'alice')
    assert token
    assert state.claim_active_account_trigger(s.a,'alice',token)
    assert state.consume_account_trigger(s.a,'alice',token)
    s.db.deactivate_workflow(s.a,owner_username='alice')
    assert s.module.activate_account_workflow(s.a,'alice','a-key')[1]==409
    assert not s.db.get_workflow(s.a).is_active


def test_restart_registration_restores_only_armed_rows(claims,monkeypatch):
    m,state,arm=claims;s=m.s
    arm('orderUpdateTrigger')
    token=state.get_account_trigger_arm(s.a,'alice')
    assert state.claim_active_account_trigger(s.a,'alice',token)
    s.db.engine.dispose()
    register=Mock(return_value=True)
    monkeypatch.setattr(m.order.flow_order_update_monitor,'add_watch',register)
    assert m.order.restore_order_update_watches()==1
    assert register.call_args.kwargs['workflow_id']==s.b
    assert register.call_args.kwargs['user_id']=='bob'
    assert state.get_account_trigger_state(s.a,'alice')=='claimed'
    s.clients['a-key'].place_order.assert_not_called()
    s.clients['b-key'].place_order.assert_not_called()


def test_missing_event_and_inactive_workflow_do_not_spend_arm(claims):
    m,state,arm=claims;s=m.s
    arm('priceAlert')
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_TRIGGER_EVENT_REQUIRED'
    assert state.get_account_trigger_state(s.a,'alice')=='armed'
    s.db.deactivate_workflow(s.a,owner_username='alice')
    assert s.engine.execute_workflow(s.a,webhook_data={'trigger_type':'price_alert'},api_key='a-key')['code']=='FLOW_TRIGGER_NOT_ARMED'
    assert state.get_account_trigger_state(s.a,'alice')=='armed'
    s.clients['a-key'].place_order.assert_not_called()


def test_failed_broker_attempt_is_consumed_without_automatic_retry(claims):
    m,state,arm=claims;s=m.s
    arm('priceAlert')
    s.clients['a-key'].place_order.side_effect=RuntimeError('unknown broker outcome')
    result=s.engine.execute_workflow(s.a,webhook_data={'trigger_type':'price_alert','trigger_price':150},api_key='a-key')
    assert result['status']=='error' and result['execution_id']
    assert state.get_account_trigger_state(s.a,'alice')=='consumed'
    assert not s.db.get_workflow(s.a).is_active
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_TRIGGER_NOT_ARMED'
    assert s.clients['a-key'].place_order.call_count==1


def test_registration_failure_keeps_same_unclaimed_arm_for_retry(activation):
    s=activation
    sys.modules.pop('database.account_flow_trigger_db',None)
    state=importlib.import_module('database.account_flow_trigger_db')
    row=s.db.get_workflow(s.a)
    nodes=[{**row.nodes[0],'type':'priceAlert','data':{'symbol':'BHEL','exchange':'NSE',
        'price':100,'condition':'greater_than','trigger':'once'}},row.nodes[1]]
    s.db.update_workflow(s.a,nodes=nodes)
    s.register.side_effect=RuntimeError('registration unavailable')
    assert s.module.activate_account_workflow(s.a,'alice','a-key')[1]==503
    token=state.get_account_trigger_arm(s.a,'alice')
    assert token and not s.db.get_workflow(s.a).is_active
    s.register.side_effect=None
    assert s.module.activate_account_workflow(s.a,'alice','a-key')[1]==200
    assert state.get_account_trigger_arm(s.a,'alice')==token


@pytest.mark.parametrize('failure',['consume','stand_down'])
def test_completion_persistence_failure_reports_cleanup_and_blocks_replay(claims,monkeypatch,failure):
    m,state,arm=claims;s=m.s
    arm('priceAlert')
    if failure=='consume':
        monkeypatch.setattr(state,'consume_account_trigger',Mock(return_value=False))
    else:
        monkeypatch.setattr(s.db,'deactivate_workflow',Mock(return_value=None))
    result=s.engine.execute_workflow(s.a,webhook_data={'trigger_type':'price_alert','trigger_price':150},api_key='a-key')
    assert result['cleanup_pending'] is True
    assert state.get_account_trigger_state(s.a,'alice')==('claimed' if failure=='consume' else 'consumed')
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_TRIGGER_NOT_ARMED'
    assert s.clients['a-key'].place_order.call_count==1
