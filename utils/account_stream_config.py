"""Per-account WebSocket configuration; no global credential fallback."""
import os


def own_groww_config(username, auth_record):
    if not isinstance(username, str) or not username:
        return None
    if (auth_record is None or auth_record.name != username
            or auth_record.is_revoked or auth_record.broker != 'groww'):
        return None
    if 'groww' not in {b.strip() for b in os.getenv('VALID_BROKERS', '').split(',')}:
        return None
    from database.account_broker_db import get_groww_credentials
    credentials = get_groww_credentials(username)
    if not credentials:
        return None
    key, secret = credentials
    return {'broker_name': 'groww', 'api_key': key, 'api_secret': secret}
