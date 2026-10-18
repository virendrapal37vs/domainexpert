"""Fresh DB fingerprints for authenticated proxy identities; no plaintext retained."""
import hashlib


def proxy_auth_stamp(username, broker, presented_key=None):
    from database.auth_db import ApiKeys, Auth, PEPPER, db_session, ph, decrypt_token
    from database.user_db import User
    if not isinstance(username, str) or not username or not broker:
        return None
    try:
        row = (db_session.query(ApiKeys.api_key_hash, Auth.auth)
               .join(Auth, Auth.name == ApiKeys.user_id)
               .join(User, User.username == ApiKeys.user_id)
               .filter(ApiKeys.user_id == username, Auth.broker == broker,
                       Auth.is_revoked.is_(False)).first())
        if not row or not row[0] or not row[1]:
            return None
        if presented_key is not None:
            if not isinstance(presented_key, str) or not presented_key:
                return None
            ph.verify(row[0], presented_key + PEPPER)
        token = decrypt_token(row[1])
        if not token:
            return None
        return hashlib.sha256((row[0] + '\0' + token + '\0' + broker).encode()).hexdigest()
    except Exception:
        return None
    finally:
        db_session.remove()
