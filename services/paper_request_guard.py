"""Durable, fail-closed claims for staging paper order requests."""
import secrets
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadData
from sqlalchemy import Column, MetaData, String, Table, insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

metadata = MetaData()
claims = Table('staging_paper_request_claims', metadata,
    Column('request_id', String(64), primary_key=True),
    Column('owner', String(255), nullable=False),
    Column('kind', String(16), nullable=False))


def serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='staging-paper-order-v1')


def issue_token(owner, kind):
    return serializer().dumps(dict(owner=owner, kind=kind, request_id=secrets.token_hex(32)))


def claim_request(token, owner, kind):
    if not isinstance(token, str) or len(token) > 2048:
        return 'Reload the paper page to get a new request token.', 400
    try:
        data = serializer().loads(token, max_age=3600)
        if (not isinstance(data, dict) or data.get('owner') != owner or data.get('kind') != kind
                or not isinstance(data.get('request_id'), str) or len(data['request_id']) != 64):
            raise ValueError()
    except (BadData, ValueError):
        return 'Invalid or expired paper request. Reload the paper page.', 400
    from database.sandbox_db import engine
    try:
        claims.create(engine, checkfirst=True)
        # Commit before any quote, fund or order side effect. Never release a
        # claim: an interrupted request has an uncertain outcome and needs review.
        with engine.begin() as connection:
            connection.execute(insert(claims).values(request_id=data['request_id'], owner=owner, kind=kind))
    except IntegrityError:
        return 'This paper request was already submitted. Check recent orders before starting a new request.', 409
    except SQLAlchemyError:
        return 'Paper request protection unavailable. No new order was started.', 503
    return None
