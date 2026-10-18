"""Internal account envelope for broker market data; never trust tick owner fields."""
from database.account_broker_db import per_user_groww_enabled


def pack_account_tick(owner, data):
    if not per_user_groww_enabled():
        return data
    if not isinstance(owner, str) or not owner or not isinstance(data, dict):
        raise ValueError('Account market data requires an adapter owner')
    return {'_domainxpert_account_tick': 1, 'owner': owner, 'data': data}


def unpack_account_tick(payload):
    if not per_user_groww_enabled():
        return None, payload
    if (not isinstance(payload, dict)
            or payload.get('_domainxpert_account_tick') != 1
            or not isinstance(payload.get('owner'), str)
            or not payload['owner']
            or not isinstance(payload.get('data'), dict)):
        return None, None
    return payload['owner'], payload['data']
