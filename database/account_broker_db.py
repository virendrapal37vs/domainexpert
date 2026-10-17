"""Per-account Groww app credentials. Never mutate os.environ or the .env file."""
import os
from sqlalchemy import Column, String, Text
from database.user_db import Base, db_session, engine
from database.auth_db import encrypt_token, decrypt_token


class AccountBrokerCredential(Base):
    __tablename__ = "account_broker_credentials"
    username = Column(String(80), primary_key=True)
    broker = Column(String(20), primary_key=True)
    encrypted_key = Column(Text, nullable=False)
    encrypted_secret = Column(Text, nullable=False)


def per_user_groww_enabled():
    return os.getenv("DOMAINXPERT_PER_USER_GROWW", "false").lower() == "true"


def init_account_broker_db():
    AccountBrokerCredential.__table__.create(engine, checkfirst=True)


def get_groww_credentials(username):
    if not username:
        return None
    row = db_session.get(AccountBrokerCredential, (username, "groww"))
    if row is None:
        return None
    # Decryption must fail closed, never fall back to a global credential.
    key, secret = decrypt_token(row.encrypted_key), decrypt_token(row.encrypted_secret)
    if not key or not secret:
        return None
    return key, secret


def has_groww_credentials(username):
    return bool(username) and db_session.get(AccountBrokerCredential, (username, "groww")) is not None


def save_groww_credentials(username, key, secret):
    from database.user_db import find_user_by_exact_username
    if find_user_by_exact_username(username) is None:
        raise ValueError("Unknown account")
    try:
        row = db_session.get(AccountBrokerCredential, (username, "groww"))
        if row is None:
            row = AccountBrokerCredential(username=username, broker="groww")
            db_session.add(row)
        row.encrypted_key = encrypt_token(key)
        row.encrypted_secret = encrypt_token(secret)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
