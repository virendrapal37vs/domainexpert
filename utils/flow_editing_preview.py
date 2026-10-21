"""Explicit staging-only editing routes. No execution/lifecycle/transport access."""
import os
from functools import wraps
from flask import jsonify, request

EDITING_ENDPOINTS = frozenset({
    'react.react_flow_index','react.react_flow_editor','react.react_flow_shortcuts',
    'flow.preview_workflow_draft','flow.list_workflows','flow.create_workflow','flow.get_workflow','flow.update_workflow',
    'flow.export_workflow','flow.import_workflow','flow.replace_workflow',
    'flow.get_workflow_executions','flow.record_trigger_review',
})


def editing_preview_enabled():
    from utils.staging_mode import staging_safe
    return (staging_safe() and os.getenv('DOMAINXPERT_PER_USER_GROWW','false').lower() == 'true'
            and os.getenv('DOMAINXPERT_FLOW_EDITING_PREVIEW','false').lower() == 'true')


def editing_request_allowed():
    return editing_preview_enabled() and request.endpoint in EDITING_ENDPOINTS


def flow_session_required(fn):
    from utils.session import check_session_validity
    legacy = check_session_validity(fn)
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if editing_request_allowed():
            from utils.account_access import current_account
            if current_account() is None:
                return jsonify(error='Sign in first'),401
            return fn(*args, **kwargs)
        return legacy(*args, **kwargs)
    return wrapped
