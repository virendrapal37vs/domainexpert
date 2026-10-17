"""Shared scalping state is unavailable until its account migration finishes."""
import os


def shared_scalping_disabled():
    return any(os.getenv(flag, 'false').lower() == 'true'
               for flag in ('DOMAINXPERT_PER_USER_GROWW', 'DOMAINXPERT_ACCOUNT_MODES'))
