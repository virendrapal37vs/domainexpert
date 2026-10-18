"""Validate Groww workflow ownership without cached API-key identity or fallback."""


def validate_flow_execution_owner(workflow_id, api_key):
    from database.flow_db import get_workflow, get_account_workflow
    from utils.proxy_auth_state import proxy_auth_stamp
    if not isinstance(api_key, str) or not api_key:
        raise ValueError('A current account API key is required')
    workflow = get_workflow(workflow_id)
    owner = getattr(workflow, 'owner_username', None) if workflow else None
    if not owner or get_account_workflow(workflow_id, owner) is None:
        raise ValueError('An account-owned workflow is required')
    # This fresh database check verifies the exact owner's current API-key hash
    # and non-revoked broker auth. No cached/session/global-key identity.
    if not proxy_auth_stamp(owner, 'groww', api_key):
        raise ValueError('Workflow account credentials are inactive or mismatched')
    return owner
