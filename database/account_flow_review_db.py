"""Owner observations are audit records, never broker verification or re-arm."""
from sqlalchemy import select, exists, func, literal
from sqlalchemy.exc import IntegrityError

OBSERVATIONS = frozenset({'order_seen','no_order_seen','uncertain'})


def get_account_trigger_review(workflow_id, owner):
    from database.flow_db import AccountFlowTriggerReview as Review, AccountFlowTriggerState as State, engine
    from database.account_flow_trigger_db import _scope
    owned = _scope(workflow_id, owner)
    with engine.connect() as conn:
        row = conn.execute(select(Review.observation, Review.reviewed_at).join(State,
            (State.workflow_id == Review.workflow_id) &
            (State.activation_id == Review.activation_id) &
            (State.owner_username == Review.owner_username)).where(
                Review.workflow_id == workflow_id, Review.owner_username == owner, owned)).first()
    if row is None:
        return None
    return {'observation':row.observation,'reviewed_at':row.reviewed_at.isoformat()}


def record_account_trigger_review(workflow_id, owner, observation):
    if not isinstance(observation,str) or observation not in OBSERVATIONS:
        raise ValueError('Choose order_seen, no_order_seen or uncertain')
    from database.flow_db import (
        AccountFlowTriggerReview as Review, AccountFlowTriggerState as State, FlowWorkflow, engine,
    )
    from database.account_flow_trigger_db import _scope
    owned = _scope(workflow_id, owner)
    inactive = exists(select(FlowWorkflow.id).where(FlowWorkflow.id == workflow_id,
        FlowWorkflow.owner_username == owner, FlowWorkflow.is_active.is_(False)))
    source = select(State.workflow_id, State.owner_username, State.activation_id,
        # Literal observation is a bound parameter, never SQL interpolation.
        literal(observation), func.now()).where(
            State.workflow_id == workflow_id, State.owner_username == owner,
            State.state.in_(('claimed','consumed')), owned, inactive)
    try:
        with engine.begin() as conn:
            result = conn.execute(Review.__table__.insert().from_select(
                ['workflow_id','owner_username','activation_id','observation','reviewed_at'], source))
            if result.rowcount != 1:
                raise ValueError('Deactivate a claimed or consumed workflow before recording a review')
    except IntegrityError:
        # The first observation is immutable; repeated requests do not replace it.
        if get_account_trigger_review(workflow_id, owner) is None:
            raise ValueError('Review identity needs inspection') from None
    return get_account_trigger_review(workflow_id, owner)
