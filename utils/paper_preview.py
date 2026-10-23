"""Staging-only synthetic instrument context; never a broker quote provider."""
import os
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

SYMBOL = 'DXPAPER'
GROWW_PAPER_SYMBOL = 'DXBHEL'
_active = ContextVar('domainxpert_paper_preview', default=False)
ENDPOINTS = frozenset({'paper_preview.page', 'paper_preview.order', 'paper_preview.dashboard', 'paper_preview.dashboard_export', 'paper_preview.daily_pnl'})
GROWW_ENDPOINTS = frozenset({'paper_preview.dashboard_quote', 'paper_preview.groww_page', 'paper_preview.groww_quote', 'paper_preview.groww_order'})


def groww_enabled():
    return enabled() and os.getenv('DOMAINXPERT_GROWW_PAPER_PREVIEW', '').lower() == 'true'


def enabled():
    from utils.staging_mode import staging_safe
    return (staging_safe()
            and os.getenv('DOMAINXPERT_PER_USER_GROWW', '').lower() == 'true'
            and os.getenv('DOMAINXPERT_PAPER_PREVIEW', '').lower() == 'true')


def request_allowed():
    from flask import request
    return ((enabled() and request.endpoint in ENDPOINTS)
            or (groww_enabled() and request.endpoint in GROWW_ENDPOINTS))


@contextmanager
def instrument_context():
    if not enabled():
        raise RuntimeError('Restricted paper preview required')
    token = _active.set(True)
    try:
        yield
    finally:
        _active.reset(token)


def get_symbol_info(symbol, exchange):
    if _active.get() and enabled() and exchange == 'NSE' and (symbol == SYMBOL or (groww_enabled() and symbol == GROWW_PAPER_SYMBOL)):
        return SimpleNamespace(lotsize=1, contract_value=1)
    from database.token_db import get_symbol_info as real_symbol_info
    return real_symbol_info(symbol, exchange)


def synthetic_order(symbol):
    return _active.get() and enabled() and (symbol == SYMBOL or (groww_enabled() and symbol == GROWW_PAPER_SYMBOL))
