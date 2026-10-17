# database/analyzer_db.py

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytz
from sqlalchemy import Column, DateTime, Index, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

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


class AnalyzerLog(Base):
    __tablename__ = "analyzer_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=True)
    api_type = Column(String(50), nullable=False)  # placeorder, cancelorder, etc.
    request_data = Column(Text, nullable=False)
    response_data = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

    # Performance indexes for analyzer queries
    __table_args__ = (
        Index("idx_analyzer_api_type", "api_type"),  # Speeds up filtering by API type
        Index(
            "idx_analyzer_created_at", "created_at"
        ),  # Speeds up time-based queries and log retrieval
        Index(
            "idx_analyzer_type_time", "api_type", "created_at"
        ),  # Composite for API type + time range queries
    )

    def to_dict(self):
        """Convert log entry to dictionary"""
        try:
            request_data = (
                json.loads(self.request_data)
                if isinstance(self.request_data, str)
                else self.request_data
            )
            response_data = (
                json.loads(self.response_data)
                if isinstance(self.response_data, str)
                else self.response_data
            )
        except json.JSONDecodeError:
            request_data = self.request_data
            response_data = self.response_data

        return {
            "id": self.id,
            "api_type": self.api_type,
            "request_data": request_data,
            "response_data": response_data,
            "created_at": self.created_at.astimezone(pytz.UTC).isoformat(),
        }


def init_db():
    """Initialize the analyzer table"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Analyzer DB", logger)
    ensure_log_owner_column(engine)


# Executor for asynchronous tasks
executor = ThreadPoolExecutor(10)  # Increased from 2 to 10 for better concurrency


def async_log_analyzer(request_data, response_data, api_type="placeorder", api_key=None):
    """Asynchronously log analyzer request"""
    try:
        # Serialize JSON data for storage
        request_json = json.dumps(request_data)
        response_json = json.dumps(response_data)

        # Get current time in IST
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        username = None
        if api_key:
            from database.auth_db import verify_api_key
            username = verify_api_key(api_key)
        analyzer_log = AnalyzerLog(
            username=username,
            api_type=api_type,
            request_data=request_json,
            response_data=response_json,
            created_at=now_ist,
        )
        db_session.add(analyzer_log)
        db_session.commit()
    except Exception as e:
        logger.exception(f"Error saving analyzer log: {e}")
        db_session.rollback()
    finally:
        db_session.remove()


def ensure_log_owner_column(target_engine):
    """Additive migration; old logs stay ownerless rather than guessing owners."""
    columns = {column['name'] for column in inspect(target_engine).get_columns('analyzer_logs')}
    if 'username' not in columns:
        with target_engine.begin() as connection:
            connection.execute(text('ALTER TABLE analyzer_logs ADD COLUMN username VARCHAR(80)'))


def account_analyzer_query(*, username=None, api_key=None):
    from database.account_broker_db import per_user_groww_enabled
    query = db_session.query(AnalyzerLog)
    if per_user_groww_enabled():
        from utils.account_mode_context import resolve_mode_owner
        owner = resolve_mode_owner(username=username, api_key=api_key)
        return query.filter(AnalyzerLog.username == owner)
    return query
