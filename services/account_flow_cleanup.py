"""Delete an inactive account-owned Flow only after acknowledged cleanup."""


def delete_account_workflow(workflow_id, owner_username):
    from database.flow_db import get_account_workflow, delete_workflow
    from services.flow_executor_service import (
        get_workflow_lock, release_workflow_subscriptions, has_workflow_subscriptions,
    )
    workflow = get_account_workflow(workflow_id, owner_username)
    if workflow is None:
        return {'error': 'Workflow not found'}, 404
    lock = get_workflow_lock(workflow_id)
    if not lock.acquire(blocking=False):
        return {'error': 'Workflow is still running. Try again when it finishes.'}, 409
    try:
        workflow = get_account_workflow(workflow_id, owner_username)
        if workflow is None:
            return {'error': 'Workflow not found'}, 404
        # Active execution/activation has not yet been migrated. Never delete
        # an active graph even if its current process lock happens to be free.
        if workflow.is_active:
            return {'error': 'Deactivate the workflow before account deletion.'}, 409
        try:
            from services.flow_scheduler_service import get_flow_scheduler
            from services.flow_price_monitor_service import get_flow_price_monitor
            from services.flow_order_update_monitor_service import get_flow_order_update_monitor
            get_flow_scheduler().remove_workflow_job(
                workflow_id, strict=True, owner_username=owner_username)
            get_flow_price_monitor().remove_alert(workflow_id, owner_username=owner_username)
            get_flow_order_update_monitor().remove_watch(workflow_id, owner_username=owner_username)
            release_workflow_subscriptions(workflow_id, owner_username=owner_username)
            if has_workflow_subscriptions(workflow_id):
                return {'error': 'Workflow subscriptions still need cleanup. Retry later.'}, 503
            if not delete_workflow(workflow_id, owner_username=owner_username):
                return {'error': 'Workflow deletion failed. Retry later.'}, 503
        except Exception:
            # Previously completed removals are idempotent; retain the row and
            # its credentials so a failed step can be retried without borrowing
            # any other account identity. Do not expose internal errors.
            return {'error': 'Workflow cleanup failed. Retry later.'}, 503
        return {'status': 'success', 'message': 'Workflow deleted'}, 200
    finally:
        lock.release()
