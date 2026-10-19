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
    if any(n.get('type') in ('priceAlert','orderUpdateTrigger')
           and (n.get('data') or {}).get('trigger','once') != 'every_time'
           for n in workflow.nodes):
        return {'status':'error','code':'FLOW_NODE_NOT_ACCOUNT_READY',
                'message':'Account price/order triggers currently require every_time mode.'}
    from services.flow_openalgo_client import get_flow_client
    from services.flow_executor_service import _execute_workflow_graph
    def factory(key):
        # Never replace the key admitted for this run with a key from graph data.
        if key != api_key:
            raise ValueError('Workflow key changed')
        return AccountFlowClient(workflow_id, owner, key, get_flow_client(key))
    return _execute_workflow_graph(workflow_id, webhook_data, api_key, client_factory=factory)
