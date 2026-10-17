# database/apilog_db.py

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytz
from sqlalchemy import Column, DateTime, Integer, Text, String, create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from utils.logging import get_logger

logger = get_logger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")  # Replace with your SQLite path

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class OrderLog(Base):
    __tablename__ = "order_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=True)
    api_type = Column(Text, nullable=False)
    request_data = Column(Text, nullable=False)
    response_data = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())


def init_db():
    """Initialize the API log database tables.

    Creates the ``order_logs`` table if it does not already exist,
    using the shared ``db_init_helper`` for consistent logging.
    """
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "API Log DB", logger)
    ensure_order_log_owner_column(engine)


# Executor for asynchronous tasks
executor = ThreadPoolExecutor(10)  # Increased from 2 to 10 for better concurrency


def async_log_order(api_type, request_data, response_data, api_key=None):
    """Persist an API order log entry to the database.

    Note: Despite its name, this function executes **synchronously**.
    It is designed to be submitted to a ``ThreadPoolExecutor`` by
    callers so that the database write does not block the main
    request thread.

    Args:
        api_type: The type of API call. Reserved values include:
            - Regular orders: ``placeorder``, ``placesmartorder``, ``modifyorder``,
              ``cancelorder``, ``cancelallorder``, ``closeposition``, ``basketorder``,
              ``splitorder``, ``optionsorder``, ``optionsmultiorder``.
            - GTT orders: ``placegttorder``, ``modifygttorder``, ``cancelgttorder``,
              ``gttorderbook``, ``gtttriggered`` (auto-emitted when a GTT leg fires),
              ``gttexpired`` (auto-emitted when a GTT passes ``expires_at``).
            - Data reads: ``orderbook``, ``tradebook``, ``positionbook``, ``holdings``,
              ``funds``, ``orderstatus``, ``openposition``, ``quotes``, ``depth``,
              ``history``, ``chart``, etc.
        request_data: Dictionary of the original request payload.
        response_data: Dictionary of the broker/service response.
    """
    try:
        username = None
        candidate_key = api_key or (request_data.get("apikey") if isinstance(request_data, dict) else None)
        if candidate_key:
            from database.auth_db import verify_api_key
            username = verify_api_key(candidate_key)
        # Never persist the OpenAlgo API key inside new request log payloads.
        safe_request = dict(request_data) if isinstance(request_data, dict) else request_data
        if isinstance(safe_request, dict):
            safe_request.pop("apikey", None)
        request_json = json.dumps(safe_request)
        response_json = json.dumps(response_data)

        # Get current time in IST
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        order_log = OrderLog(
            username=username,
            api_type=api_type,
            request_data=request_json,
            response_data=response_json,
            created_at=now_ist,
        )
        db_session.add(order_log)
        db_session.commit()
    except Exception as e:
        logger.exception(f"Error saving order log: {e}")
        db_session.rollback()
    finally:
        db_session.remove()


def ensure_order_log_owner_column(target_engine):
    columns = {column['name'] for column in inspect(target_engine).get_columns('order_logs')}
    if 'username' not in columns:
        with target_engine.begin() as connection:
            connection.execute(text('ALTER TABLE order_logs ADD COLUMN username VARCHAR(80)'))


def account_order_log_query(*, username=None, api_key=None):
    from database.account_broker_db import per_user_groww_enabled
    query = db_session.query(OrderLog)
    if per_user_groww_enabled():
        from utils.account_mode_context import resolve_mode_owner
        owner = resolve_mode_owner(username=username, api_key=api_key)
        return query.filter(OrderLog.username == owner)
    return query
