"""Fresh subscription checks for API authentication and proxy delivery."""


def subscription_access_allowed(username):
    from services import manual_subscription as billing
    if not billing.enabled():
        return True
    # Test/manual staging grants must never authorize production execution.
    from utils.staging_mode import staging_safe
    if not staging_safe() or not isinstance(username, str) or not username:
        return False
    try:
        from sqlalchemy import select
        from types import SimpleNamespace
        from database.user_db import User, engine
        # Core query avoids a stale ORM identity when the owner role changes.
        with engine.connect() as conn:
            row = conn.execute(select(User.username, User.email, User.is_admin)
                               .where(User.username == username)).mappings().first()
            if row is None:
                return False
            if billing.exempt(SimpleNamespace(**row)):
                return True
            until = billing.access_until(username, conn)
        from datetime import datetime
        return bool(until and datetime.fromisoformat(until) > billing.now())
    except Exception:
        # Missing ledger, unavailable DB or malformed expiry cannot grant access.
        return False
