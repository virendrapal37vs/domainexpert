"""Deletion orchestration with real owner-scoped SQLite rows and fake cleanup services."""
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows


@pytest.fixture
def cleanup(flows,monkeypatch):
    a = flows.create_workflow('Alice',owner_username='alice')
    b = flows.create_workflow('Bob',owner_username='bob')
    lock = threading.Lock()
    release = Mock()
    pending = Mock(return_value=False)
    scheduler,price,order = Mock(),Mock(),Mock()
    monkeypatch.setitem(sys.modules,'services.flow_executor_service',SimpleNamespace(
        get_workflow_lock=lambda wid: lock,release_workflow_subscriptions=release,
        has_workflow_subscriptions=pending))
    for name,factory,service in [('flow_scheduler_service','get_flow_scheduler',scheduler),
        ('flow_price_monitor_service','get_flow_price_monitor',price),
        ('flow_order_update_monitor_service','get_flow_order_update_monitor',order)]:
        monkeypatch.setitem(sys.modules,'services.'+name,SimpleNamespace(**{factory:lambda obj=service:obj}))
    from services.account_flow_cleanup import delete_account_workflow
    return SimpleNamespace(db=flows,a=a.id,b=b.id,lock=lock,release=release,pending=pending,
        scheduler=scheduler,price=price,order=order,delete=delete_account_workflow)


def test_wrong_owner_cannot_touch_any_cleanup_service(cleanup):
    c=cleanup
    assert c.delete(c.b,'alice')[1] == 404
    assert not c.scheduler.mock_calls and not c.price.mock_calls and not c.order.mock_calls
    c.release.assert_not_called()
    assert c.db.get_workflow(c.b)


def test_success_passes_same_owner_to_every_step_and_keeps_bob(cleanup):
    c=cleanup
    assert c.delete(c.a,'alice')[1] == 200
    c.scheduler.remove_workflow_job.assert_called_once_with(c.a,strict=True,owner_username='alice')
    c.price.remove_alert.assert_called_once_with(c.a,owner_username='alice')
    c.order.remove_watch.assert_called_once_with(c.a,owner_username='alice')
    c.release.assert_called_once_with(c.a,owner_username='alice')
    assert c.db.get_workflow(c.a) is None
    assert c.db.get_workflow(c.b)
    assert not c.lock.locked()


@pytest.mark.parametrize('step',['scheduler','price','order','release'])
def test_failed_cleanup_retains_row_and_releases_lock(cleanup,step):
    c=cleanup
    action={'scheduler':c.scheduler.remove_workflow_job,'price':c.price.remove_alert,
            'order':c.order.remove_watch,'release':c.release}[step]
    action.side_effect=RuntimeError('synthetic internal secret')
    payload,status=c.delete(c.a,'alice')
    assert status == 503
    assert 'secret' not in str(payload)
    assert c.db.get_workflow(c.a) and c.db.get_workflow(c.b)
    assert not c.lock.locked()


def test_pending_subscription_preserves_row_for_retry(cleanup):
    c=cleanup
    c.pending.return_value=True
    assert c.delete(c.a,'alice')[1] == 503
    assert c.db.get_workflow(c.a)
    c.pending.return_value=False
    assert c.delete(c.a,'alice')[1] == 200


def test_running_lock_and_active_workflow_both_rejected(cleanup):
    c=cleanup
    c.lock.acquire()
    assert c.delete(c.a,'alice')[1] == 409
    c.lock.release()
    c.db.update_workflow(c.a,owner_username='alice',is_active=True)
    assert c.delete(c.a,'alice')[1] == 409
    assert not c.scheduler.mock_calls
    assert c.db.get_workflow(c.a)
