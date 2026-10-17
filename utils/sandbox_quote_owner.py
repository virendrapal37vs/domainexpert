"""Owner-scoped sandbox quotes; missing accounts never borrow another key."""
import os


def scoped_quotes_enabled():
    return os.getenv('DOMAINXPERT_PER_USER_GROWW', 'false').lower() == 'true'


def quote_api_key(username):
    if scoped_quotes_enabled():
        if not isinstance(username, str) or not username:
            return None
        from database.auth_db import get_api_key_for_tradingview
        return get_api_key_for_tradingview(username)
    from database.auth_db import ApiKeys, decrypt_token
    row = ApiKeys.query.first()
    return decrypt_token(row.api_key_encrypted) if row else None


def fetch_record_quotes(engine, records):
    """Return {(owner, symbol, exchange): quote}; batch only within an owner."""
    records = list(records)
    if not scoped_quotes_enabled():
        quotes = engine._fetch_quotes_batch(list({(r.symbol, r.exchange) for r in records}))
        return {(r.user_id, r.symbol, r.exchange): quotes[(r.symbol, r.exchange)]
                for r in records if (r.symbol, r.exchange) in quotes}
    groups = {}
    for row in records:
        if isinstance(row.user_id, str) and row.user_id:
            groups.setdefault(row.user_id, set()).add((row.symbol, row.exchange))
    result = {}
    for owner, symbols in groups.items():
        quotes = engine._fetch_quotes_batch(list(symbols), user_id=owner)
        for (symbol, exchange), quote in quotes.items():
            if (symbol, exchange) in symbols:
                result[(owner, symbol, exchange)] = quote
    return result
