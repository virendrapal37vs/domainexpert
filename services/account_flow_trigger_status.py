"""Read-only account-owned one-shot status; never exposes activation identities."""
MESSAGES = {
    'unarmed': ('Not armed', 'This one-shot trigger has no durable arm. It cannot execute until activated.'),
    'armed': ('Armed', 'This one-shot trigger is unused. It can fire while the workflow is active.'),
    'claimed': ('Execution claimed', 'Execution may still be running or its outcome may be uncertain. Check execution history and broker orders before taking further action. Automatic retry is blocked.'),
    'consumed': ('Trigger used', 'This one-shot trigger has been used. Review execution history and broker orders for the outcome. Automatic re-arm is blocked.'),
    'unavailable': ('Status unavailable', 'The saved trigger state is not recognized. Execution needs review.'),
}


def get_account_one_shot_status(workflow_id, owner):
    from database.flow_db import get_account_workflow
    from database.account_flow_trigger_db import get_account_trigger_state
    row = get_account_workflow(workflow_id, owner)
    if row is None:
        raise ValueError('Account-owned workflow required')
    if not any(n.get('type') in ('priceAlert','orderUpdateTrigger')
               and (n.get('data') or {}).get('trigger','once') == 'once'
               for n in (row.nodes or [])):
        return None
    state = get_account_trigger_state(workflow_id, owner) or 'unarmed'
    if state not in MESSAGES:
        state = 'unavailable'
    label, message = MESSAGES[state]
    from database.account_flow_review_db import get_account_trigger_review
    return {'state':state, 'label':label, 'message':message,
            'review':get_account_trigger_review(workflow_id, owner)}
