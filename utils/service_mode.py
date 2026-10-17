"""Explicit key propagation for API/background service mode decisions."""
from utils.account_mode_context import account_modes_enabled


def service_analyze_mode(api_key=None):
    from database.settings_db import get_analyze_mode
    if account_modes_enabled():
        return get_analyze_mode(api_key=api_key) if api_key is not None else get_analyze_mode()
    return get_analyze_mode()
