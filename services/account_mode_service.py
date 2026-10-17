"""Account mode transition without stopping shared sandbox workers."""
from database.account_mode_db import get_account_analyze_mode, set_account_analyze_mode
from utils.account_mode_context import resolve_mode_owner


def ensure_account_sandbox():
    from utils.staging_mode import staging_safe
    if staging_safe():
        raise RuntimeError('Sandbox workers are disabled in restricted staging')
    from sandbox.execution_thread import start_execution_engine
    from sandbox.squareoff_thread import start_squareoff_scheduler
    success, _message = start_execution_engine()
    if not success:
        raise RuntimeError('Unable to start sandbox execution engine')
    result = start_squareoff_scheduler()
    if isinstance(result, tuple) and not result[0]:
        raise RuntimeError('Unable to start sandbox square-off scheduler')


def change_account_mode(new_mode=None, *, toggle=False, username=None, api_key=None):
    from utils.staging_mode import staging_safe
    if staging_safe():
        raise RuntimeError('Mode transitions are disabled in restricted staging')
    owner = resolve_mode_owner(username=username, api_key=api_key)
    if not toggle and not isinstance(new_mode, bool):
        raise ValueError('Mode must be boolean')
    # Use the existing bounded transition lock. One worker remains required.
    from services.analyzer_service import mode_transition
    with mode_transition():
        current = get_account_analyze_mode(owner)
        target = not current if toggle else new_mode
        # Keep workers running even if this user switches Live: other users and
        # already-open sandbox positions/orders still need execution/square-off.
        ensure_account_sandbox()
        set_account_analyze_mode(owner, target)
        return get_account_analyze_mode(owner)
