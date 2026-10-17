"""Shared strategy risk feed is not yet an account-owned execution service."""
import os


def shared_strategy_disabled():
    return any(os.getenv(flag, 'false').lower() == 'true'
               for flag in ('DOMAINXPERT_PER_USER_GROWW', 'DOMAINXPERT_ACCOUNT_MODES'))


STRATEGY_UNAVAILABLE = 'Strategy execution is unavailable until the shared risk feed is migrated to account ownership.'
