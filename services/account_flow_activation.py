"""Account-owned Flow activation. HTTP/execution feature guards remain enabled."""


def remove_account_triggers(workflow_id, owner):
    from services.flow_scheduler_service import get_flow_scheduler
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    # Missing registrations return False normally. Real removal failures raise.
    get_flow_scheduler().remove_workflow_job(workflow_id, strict=True, owner_username=owner)
    get_flow_price_monitor().remove_alert(workflow_id, owner_username=owner)
    get_flow_order_update_monitor().remove_watch(workflow_id, owner_username=owner)


def register_account_trigger(workflow, trigger, owner, api_key):
    from utils.flow_execution_owner import validate_flow_execution_owner
    if workflow.owner_username != owner or validate_flow_execution_owner(workflow.id, api_key) != owner:
        raise ValueError('Trigger requires its workflow owner')
    kind, data = trigger['type'], trigger.get('data') or {}
    if kind in ('priceAlert','orderUpdateTrigger') and data.get('trigger','once') != 'every_time':
        raise ValueError('Account price/order triggers currently require every_time mode')
    if kind == 'start':
        schedule = data.get('scheduleType')
        if schedule and schedule != 'manual':
            from services.flow_scheduler_service import get_flow_scheduler
            from database.flow_db import set_schedule_job_id
            job = get_flow_scheduler().add_workflow_job(
                workflow_id=workflow.id, schedule_type=schedule,
                time_str=data.get('time', '09:15'), days=data.get('days'),
                execute_at=data.get('executeAt'), interval_value=data.get('intervalValue'),
                interval_unit=data.get('intervalUnit'),
                market_hours_only=bool(data.get('marketHoursOnly', False)), owner_username=owner)
            if not set_schedule_job_id(workflow.id, job):
                raise RuntimeError('Could not persist workflow schedule')
    elif kind == 'priceAlert':
        from services.flow_price_monitor_service import get_flow_price_monitor
        ok = get_flow_price_monitor().add_alert(
            workflow_id=workflow.id, symbol=data.get('symbol',''), exchange=data.get('exchange','NSE'),
            condition=data.get('condition','greater_than'), target_price=float(data.get('price',0) or 0),
            price_lower=data.get('priceLower'), price_upper=data.get('priceUpper'),
            percentage=data.get('percentage'), api_key=api_key,
            trigger=data.get('trigger','once'), expiration=data.get('expiration','none'))
        if not ok:
            raise RuntimeError('Price monitor refused workflow')
    elif kind == 'orderUpdateTrigger':
        from services.flow_order_update_monitor_service import get_flow_order_update_monitor
        ok = get_flow_order_update_monitor().add_watch(
            workflow_id=workflow.id, api_key=api_key, user_id=owner,
            order_id=data.get('orderId') or None, symbol=data.get('symbol') or None,
            exchange=data.get('exchange') or None, status=data.get('status','complete'),
            trigger=data.get('trigger','once'))
        if not ok:
            raise RuntimeError('Order monitor refused workflow')
    elif kind != 'webhookTrigger':
        raise ValueError('Unsupported workflow trigger')


def activate_account_workflow(workflow_id, owner, api_key):
    from database.flow_db import get_account_workflow, activate_workflow, deactivate_workflow, set_schedule_job_id
    from services.flow_executor_service import get_workflow_lock
    from services.flow_workflow_validator import validate_workflow
    from utils.flow_execution_owner import validate_flow_execution_owner
    workflow = get_account_workflow(workflow_id, owner)
    if workflow is None:
        return {'error':'Workflow not found'},404
    lock = get_workflow_lock(workflow_id)
    if not lock.acquire(blocking=False):
        return {'error':'Workflow is still running'},409
    try:
        workflow = get_account_workflow(workflow_id, owner)
        if workflow is None:
            return {'error':'Workflow not found'},404
        try:
            if validate_flow_execution_owner(workflow_id, api_key) != owner:
                raise ValueError('Owner mismatch')
        except ValueError:
            return {'error':'Current workflow-owner credentials are required'},403
        errors = validate_workflow({'name':workflow.name,'nodes':workflow.nodes or [],'edges':workflow.edges or []})
        if errors:
            return {'error':'Workflow graph is invalid','errors':errors},400
        trigger = next((n for n in workflow.nodes if n.get('type') in
                        ('start','webhookTrigger','priceAlert','orderUpdateTrigger')),None)
        if trigger is None:
            return {'error':'Workflow requires a trigger'},400
        if workflow.is_active:
            return {'status':'already_active'},200
        try:
            # Remove any stale inactive registrations before persisting active.
            remove_account_triggers(workflow_id, owner)
        except Exception:
            return {'error':'Stale trigger cleanup failed. Retry later.'},503
        try:
            workflow = activate_workflow(workflow_id, api_key=api_key, owner_username=owner)
            if workflow is None:
                raise RuntimeError('Activation persistence failed')
            register_account_trigger(workflow, trigger, owner, api_key)
            return {'status':'success','message':'Workflow activated'},200
        except Exception:
            # First stand down the row so queued triggers cannot start new runs.
            # Keep credentials available for repair/retry if cleanup fails.
            try:
                inactive = deactivate_workflow(workflow_id, owner_username=owner)
            except Exception:
                inactive = None
            cleanup_pending = inactive is None
            try:
                remove_account_triggers(workflow_id, owner)
                if inactive is not None:
                    if not set_schedule_job_id(workflow_id, None):
                        cleanup_pending = True
            except Exception:
                cleanup_pending = True
            return {'error':'Workflow activation failed','cleanup_pending':cleanup_pending},503
    finally:
        lock.release()


def deactivate_account_workflow(workflow_id, owner):
    """Stand down before cleanup; owner authorization does not need a broker key."""
    from database.flow_db import get_account_workflow, deactivate_workflow, set_schedule_job_id
    from services.flow_executor_service import (
        get_workflow_lock, release_workflow_subscriptions, has_workflow_subscriptions,
    )
    if get_account_workflow(workflow_id, owner) is None:
        return {'error':'Workflow not found'},404
    lock = get_workflow_lock(workflow_id)
    if not lock.acquire(blocking=False):
        return {'error':'Workflow is still running'},409
    try:
        if get_account_workflow(workflow_id, owner) is None:
            return {'error':'Workflow not found'},404
        try:
            if deactivate_workflow(workflow_id, owner_username=owner) is None:
                return {'error':'Could not persist inactive state'},503
            remove_account_triggers(workflow_id, owner)
            release_workflow_subscriptions(workflow_id, owner_username=owner)
            if has_workflow_subscriptions(workflow_id):
                return {'error':'Workflow is inactive but subscription cleanup needs retry',
                        'cleanup_pending':True},503
            if not set_schedule_job_id(workflow_id, None):
                raise RuntimeError('Could not clear schedule marker')
        except Exception:
            return {'error':'Workflow cleanup failed. Retry later.','cleanup_pending':True},503
        return {'status':'success','message':'Workflow deactivated'},200
    finally:
        lock.release()
