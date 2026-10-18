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


def account_flow_trigger_allowed(workflow_id, api_key=None):
    """Validate a background trigger, retaining the account execution block."""
    from utils.strategy_account_guard import shared_strategy_disabled
    if not shared_strategy_disabled():
        return True
    flow_db = None
    try:
        from database import flow_db
        # Persistent schedules intentionally carry no plaintext API key. Read
        # only this workflow's stored key; never use a global or session key.
        if api_key is None:
            workflow = flow_db.get_workflow(workflow_id)
            api_key = flow_db.get_workflow_api_key(workflow)
        validate_flow_execution_owner(workflow_id, api_key)
    except Exception:
        return False
    finally:
        if flow_db is not None:
            flow_db.db_session.remove()
    # Owner verification alone does not certify graph execution/monitors.
    return False
