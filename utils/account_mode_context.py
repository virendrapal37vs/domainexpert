"""Resolve mode ownership without falling back to global Live mode."""
import os
from flask import has_request_context, request, session


def account_modes_enabled():
    return os.getenv('DOMAINXPERT_ACCOUNT_MODES', 'false').lower() == 'true'


def resolve_mode_owner(*, username=None, api_key=None):
    from database.auth_db import verify_api_key
    from database.user_db import find_user_by_exact_username
    if api_key is not None:
        owner = verify_api_key(api_key) if isinstance(api_key, str) and api_key else None
        if not owner or (username is not None and owner != username):
            raise ValueError('Valid matching API key owner required')
    elif username is not None:
        owner = username
    elif has_request_context():
        data = request.get_json(silent=True) if request.is_json else None
        supplied_key = data.get('apikey') if isinstance(data, dict) else None
        if supplied_key is not None:
            return resolve_mode_owner(api_key=supplied_key)
        # API routes must never borrow the browser's signed-in account.
        if request.path.startswith('/api/'):
            raise ValueError('API key owner required')
        owner = session.get('user')
    else:
        raise ValueError('Explicit mode owner required outside a request')
    if not isinstance(owner, str) or not owner or find_user_by_exact_username(owner) is None:
        raise ValueError('Existing mode owner required')
    return owner


def read_account_mode(*, username=None, api_key=None):
    from database.account_mode_db import get_account_analyze_mode
    return get_account_analyze_mode(resolve_mode_owner(username=username, api_key=api_key))
