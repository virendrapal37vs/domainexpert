"""Durable first-arm claims for account monitor execution.

An interrupted claim remains claimed. Retrying it could duplicate an order.
No automatic reset/re-arm or broker execution is performed by these helpers.
"""
import secrets
from sqlalchemy import select, update, exists
from sqlalchemy.exc import IntegrityError


def _verified_workflow_owner(owner):
    from database.flow_db import _verified_workflow_owner as verify
    return verify(owner)


def _scope(workflow_id, owner):
    from database.flow_db import FlowWorkflow
    _verified_workflow_owner(owner)
    if not isinstance(workflow_id, int) or isinstance(workflow_id, bool) or workflow_id <= 0:
        raise ValueError('A workflow ID is required')
    return exists(select(FlowWorkflow.id).where(
        FlowWorkflow.id == workflow_id, FlowWorkflow.owner_username == owner))


def create_account_trigger_arm(workflow_id, owner):
    """Create the first arm only. Existing state is never reset implicitly."""
    from database.flow_db import AccountFlowTriggerState as State, FlowWorkflow, engine
    owned = _scope(workflow_id, owner)
    token = secrets.token_hex(32)
    with engine.begin() as conn:
        if not conn.scalar(select(owned)):
            raise ValueError('An account-owned workflow is required')
        try:
            # Unique workflow ID serializes competing first-arm attempts.
            with conn.begin_nested():
                conn.execute(State.__table__.insert().values(workflow_id=workflow_id,
                    owner_username=owner, activation_id=token, state='armed'))
        except IntegrityError:
            return None
    return token


def _transition(workflow_id, owner, token, before, after):
    from database.flow_db import AccountFlowTriggerState as State, FlowWorkflow, engine
    owned = _scope(workflow_id, owner)
    if not isinstance(token, str) or not token:
        return False
    with engine.begin() as conn:
        result = conn.execute(update(State).where(State.workflow_id == workflow_id,
            State.owner_username == owner, State.activation_id == token,
            State.state == before, owned).values(state=after))
        return result.rowcount == 1


def claim_account_trigger(workflow_id, owner, token):
    return _transition(workflow_id, owner, token, 'armed', 'claimed')


def consume_account_trigger(workflow_id, owner, token):
    return _transition(workflow_id, owner, token, 'claimed', 'consumed')


def get_account_trigger_state(workflow_id, owner):
    from database.flow_db import AccountFlowTriggerState as State, FlowWorkflow, engine
    owned = _scope(workflow_id, owner)
    with engine.connect() as conn:
        return conn.scalar(select(State.state).where(State.workflow_id == workflow_id,
            State.owner_username == owner, owned))


def get_account_trigger_arm(workflow_id, owner):
    """Only an unclaimed first activation may be registered or restored."""
    from database.flow_db import AccountFlowTriggerState as State, FlowWorkflow, engine
    owned = _scope(workflow_id, owner)
    with engine.connect() as conn:
        return conn.scalar(select(State.activation_id).where(State.workflow_id == workflow_id,
            State.owner_username == owner, State.state == 'armed', owned))


def claim_active_account_trigger(workflow_id, owner, token):
    from database.flow_db import AccountFlowTriggerState as State, FlowWorkflow, engine
    owned = _scope(workflow_id, owner)
    active = exists(select(FlowWorkflow.id).where(FlowWorkflow.id == workflow_id,
        FlowWorkflow.owner_username == owner, FlowWorkflow.is_active.is_(True)))
    if not isinstance(token, str) or not token:
        return False
    with engine.begin() as conn:
        result = conn.execute(update(State).where(State.workflow_id == workflow_id,
            State.owner_username == owner, State.activation_id == token,
            State.state == 'armed', owned, active).values(state='claimed'))
        return result.rowcount == 1
