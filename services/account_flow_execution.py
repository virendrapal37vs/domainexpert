"""Opt-in account Flow execution for a deliberately small node capability set."""
import os

SUPPORTED_ACCOUNT_NODES = frozenset({'start', 'webhookTrigger', 'priceAlert', 'orderUpdateTrigger', 'placeOrder', 'log'})


def account_flow_execution_enabled():
    from utils.staging_mode import staging_safe
    return (os.getenv('DOMAINXPERT_ACCOUNT_FLOW_EXECUTION','false').lower() == 'true'
            and os.getenv('DOMAINXPERT_ACCOUNT_MODES','false').lower() == 'true'
            and not staging_safe())


def blocked_result():
    return {'status':'error','code':'FLOW_ACCOUNT_ISOLATION_PENDING',
            'message':'Account-owned Flow execution is not enabled.'}


class AccountFlowClient:
    """Broker-call boundary: never use a cached owner check across graph nodes."""
    def __init__(self, workflow_id, owner, api_key, client):
        self.workflow_id, self.owner = workflow_id, owner
        self.api_key, self._client = api_key, client

    def place_order(self, **kwargs):
        if not account_flow_execution_enabled():
            raise ValueError("Account execution policy changed")
        from utils.flow_execution_owner import validate_flow_execution_owner
        if validate_flow_execution_owner(self.workflow_id, self.api_key) != self.owner:
            raise ValueError('Workflow owner changed')
        return self._client.place_order(**kwargs)


def execute_account_flow_graph(workflow_id, webhook_data, api_key):
    if not account_flow_execution_enabled():
        return blocked_result()
    from database.flow_db import get_account_workflow
    from utils.flow_execution_owner import validate_flow_execution_owner
    try:
        owner = validate_flow_execution_owner(workflow_id, api_key)
        workflow = get_account_workflow(workflow_id, owner)
        if workflow is None:
            raise ValueError('Workflow no longer belongs to owner')
    except ValueError:
        return {'status':'error','code':'FLOW_OWNER_AUTH_FAILED',
                'message':'Current workflow-owner credentials are required.'}
    if any(not isinstance(n,dict) or n.get('type') not in SUPPORTED_ACCOUNT_NODES
           for n in (workflow.nodes or [])):
        return {'status':'error','code':'FLOW_NODE_NOT_ACCOUNT_READY',
                'message':'This graph contains nodes not yet supported for account execution.'}
    monitors = [n for n in workflow.nodes if n.get('type') in ('priceAlert','orderUpdateTrigger')]
    if any((n.get('data') or {}).get('trigger','once') not in ('once','every_time') for n in monitors):
        return {'status':'error','code':'FLOW_NODE_NOT_ACCOUNT_READY',
                'message':'Unsupported account monitor trigger mode.'}
    one_shot = any((n.get('data') or {}).get('trigger','once') == 'once' for n in monitors)
    arm = None
    if one_shot:
        from database.account_flow_trigger_db import get_account_trigger_arm, claim_active_account_trigger
        arm = get_account_trigger_arm(workflow_id, owner)
        expected = 'price_alert' if monitors[0]['type'] == 'priceAlert' else 'order_update'
        if arm is not None and (not isinstance(webhook_data, dict)
                                or webhook_data.get('trigger_type') != expected):
            return {'status':'error','code':'FLOW_TRIGGER_EVENT_REQUIRED',
                    'message':'One-shot monitors require their matching trigger event.'}
        if arm is None or not claim_active_account_trigger(workflow_id, owner, arm):
            return {'status':'error','code':'FLOW_TRIGGER_NOT_ARMED',
                    'message':'One-shot trigger is inactive, claimed or consumed.'}
    from services.flow_openalgo_client import get_flow_client
    from services.flow_executor_service import _execute_workflow_graph
    def factory(key):
        # Never replace the key admitted for this run with a key from graph data.
        if key != api_key:
            raise ValueError('Workflow key changed')
        return AccountFlowClient(workflow_id, owner, key, get_flow_client(key))
    if not one_shot:
        return _execute_workflow_graph(workflow_id, webhook_data, api_key, client_factory=factory)
    # Claim commits before the graph can reach a broker. A crash or exception
    # leaves it claimed, never automatically re-armed or replayed.
    result = _execute_workflow_graph(workflow_id, webhook_data, api_key, client_factory=factory)
    if result.get('execution_id'):
        from database.account_flow_trigger_db import consume_account_trigger
        from database.flow_db import deactivate_workflow
        try:
            if not consume_account_trigger(workflow_id, owner, arm):
                raise RuntimeError('Could not consume one-shot claim')
            if deactivate_workflow(workflow_id, owner_username=owner) is None:
                raise RuntimeError('Could not stand down completed one-shot workflow')
        except Exception:
            result['cleanup_pending'] = True
    return result
