"""Require explicit database ownership before removing Flow registrations."""
from utils.strategy_account_guard import shared_strategy_disabled


def require_flow_cleanup_owner(workflow_id, owner_username):
    if not shared_strategy_disabled():
        return
    if isinstance(workflow_id, bool) or not isinstance(workflow_id, int) or workflow_id < 1:
        raise ValueError('A valid workflow ID is required for cleanup')
    from database.flow_db import get_account_workflow
    if not owner_username or get_account_workflow(workflow_id, owner_username) is None:
        raise ValueError('Flow cleanup requires the verified workflow owner')
