"""Explicit-owner mode storage. Not yet wired into trading dispatch."""
from sqlalchemy import Boolean, Column, String, update
from sqlalchemy.exc import IntegrityError
from database.user_db import Base, db_session, engine, find_user_by_exact_username


class AccountTradingMode(Base):
    __tablename__ = 'account_trading_modes'
    username = Column(String(80), primary_key=True)
    analyze_mode = Column(Boolean, nullable=False, default=True)


def init_account_mode_db():
    AccountTradingMode.__table__.create(engine, checkfirst=True)


def _require_owner(username):
    if not isinstance(username, str) or not username or find_user_by_exact_username(username) is None:
        raise ValueError('Existing account required')


def get_account_analyze_mode(username):
    _require_owner(username)
    # Query the column every time; avoid stale ORM rows and cross-worker caches.
    mode = db_session.query(AccountTradingMode.analyze_mode).filter_by(username=username).scalar()
    return True if mode is None else bool(mode)


def set_account_analyze_mode(username, mode):
    _require_owner(username)
    if not isinstance(mode, bool):
        raise ValueError('Mode must be boolean')
    try:
        result = db_session.execute(update(AccountTradingMode).where(AccountTradingMode.username == username).values(analyze_mode=mode))
        if not result.rowcount:
            db_session.add(AccountTradingMode(username=username, analyze_mode=mode))
        db_session.commit()
    except IntegrityError:
        # Concurrent first writes: the primary key prevents duplicate owners.
        db_session.rollback()
        try:
            db_session.execute(update(AccountTradingMode).where(AccountTradingMode.username == username).values(analyze_mode=mode))
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise
    except Exception:
        db_session.rollback()
        raise
