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
    """Admit only verified background triggers when account execution is enabled."""
    from utils.strategy_account_guard import shared_strategy_disabled
    if not shared_strategy_disabled():
        return True
    flow_db = None
    try:
        from database import flow_db
        # Persistent schedules intentionally carry no plaintext API key. Read
        # only this workflow's stored key; never use a global or session key.
        workflow = flow_db.get_workflow(workflow_id)
        if workflow is None or not workflow.is_active:
            return False
        if api_key is None:
            api_key = flow_db.get_workflow_api_key(workflow)
        validate_flow_execution_owner(workflow_id, api_key)
    except Exception:
        return False
    finally:
        if flow_db is not None:
            flow_db.db_session.remove()
    from services.account_flow_execution import account_flow_execution_enabled
    return account_flow_execution_enabled()


def account_monitor_restore_owner(workflow_id, api_key, data):
    """Require current policy/identity before rebuilding account monitor state."""
    from utils.strategy_account_guard import shared_strategy_disabled
    if not shared_strategy_disabled():
        return None
    if data.get("trigger", "once") != "every_time":
        raise ValueError("Account one-shot monitor recovery is not supported")
    if not account_flow_trigger_allowed(workflow_id, api_key):
        raise ValueError("Account monitor recovery is disabled or credentials are inactive")
    return validate_flow_execution_owner(workflow_id, api_key)
