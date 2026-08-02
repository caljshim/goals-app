from datetime import datetime, time

from sqlalchemy import func
from sqlmodel import Session, select

from app.auto_integration import executor
from app.auto_integration.models import (
    GoalIntegrationBinding,
    GoalMeasurement,
    IntegrationOperation,
    IntegrationProposal,
    IntegrationProvider,
    utc_now,
)
from app.auto_integration.schemas import (
    BindingCreate,
    BindingExecuteRequest,
    ExecuteRequest,
    MeasurementCapture,
)
from app.budget.goal_types import goal_period_start
from app.budget.models import Goal


class BindingError(Exception):
    pass


class BindingNotFound(BindingError):
    pass


class BindingConflict(BindingError):
    pass


def _connector_operation(
    session: Session,
    provider_slug: str,
    operation_id: str,
) -> tuple[IntegrationProvider, IntegrationOperation]:
    provider = session.exec(
        select(IntegrationProvider).where(
            IntegrationProvider.slug == provider_slug,
            IntegrationProvider.enabled.is_(True),
        )
    ).first()
    if provider is None:
        raise BindingNotFound("Connector not found")
    operation = session.exec(
        select(IntegrationOperation).where(
            IntegrationOperation.provider_id == provider.id,
            IntegrationOperation.operation_id == operation_id,
            IntegrationOperation.enabled.is_(True),
        )
    ).first()
    if operation is None:
        raise BindingNotFound("Connector operation not found")
    return provider, operation


def _validate_mapping(
    operation: IntegrationOperation,
    value_from: str,
    external_id_from: str | None,
) -> None:
    mapped = set(operation.result_mapping)
    if value_from not in mapped:
        raise BindingError("value_from is not an operation output")
    if external_id_from is not None and external_id_from not in mapped:
        raise BindingError("external_id_from is not an operation output")


def _validate_defaults(
    operation: IntegrationOperation,
    parameters: dict,
) -> None:
    properties = operation.input_schema.get("properties", {})
    unknown = set(parameters) - set(properties)
    if unknown:
        raise BindingError(
            "Unknown default parameters: " + ", ".join(sorted(unknown))
        )


def create_binding(
    session: Session,
    body: BindingCreate,
) -> GoalIntegrationBinding:
    goal = session.get(Goal, body.goal_id)
    if goal is None:
        raise BindingNotFound("Goal not found")
    if goal.kind != "numeric":
        raise BindingError("API integrations currently require a numeric goal")
    existing = session.exec(
        select(GoalIntegrationBinding).where(
            GoalIntegrationBinding.goal_id == body.goal_id
        )
    ).first()
    if existing is not None:
        raise BindingConflict("Goal already has an API integration")

    provider, operation = _connector_operation(
        session,
        body.provider,
        body.operation,
    )
    _validate_mapping(operation, body.value_from, body.external_id_from)
    _validate_defaults(operation, body.default_parameters)
    binding = GoalIntegrationBinding(
        goal_id=body.goal_id,
        provider_id=provider.id,
        operation_id=operation.id,
        metric=body.metric,
        unit=body.unit,
        aggregation=body.aggregation,
        value_from=body.value_from,
        external_id_from=body.external_id_from,
        default_parameters=body.default_parameters,
        trigger_mode=body.trigger_mode,
    )
    session.add(binding)
    session.commit()
    session.refresh(binding)
    return binding


def create_binding_from_proposal(
    session: Session,
    proposal_id: str,
) -> GoalIntegrationBinding:
    proposal = session.get(IntegrationProposal, proposal_id)
    if proposal is None:
        raise BindingNotFound("Integration proposal not found")
    if proposal.status != "approved" or proposal.provider_id is None:
        raise BindingConflict("Proposal must be approved before binding")
    if proposal.goal_id is None:
        raise BindingError("Proposal is not associated with a goal")

    existing = session.exec(
        select(GoalIntegrationBinding).where(
            GoalIntegrationBinding.goal_id == proposal.goal_id
        )
    ).first()
    if existing is not None:
        return existing

    draft = proposal.draft_json or {}
    capture = draft.get("suggested_capture") or {}
    operation_name = capture.get("operation")
    if not operation_name:
        raise BindingError("Proposal has no suggested measurement capture")
    provider = session.get(IntegrationProvider, proposal.provider_id)
    if provider is None:
        raise BindingNotFound("Approved connector not found")
    return create_binding(
        session,
        BindingCreate(
            goal_id=proposal.goal_id,
            provider=provider.slug,
            operation=operation_name,
            metric=capture.get("metric") or proposal.desired_metric,
            unit=capture.get("unit") or proposal.desired_unit,
            aggregation="sum",
            value_from=capture.get("value_from"),
            external_id_from=capture.get("external_id_from"),
            trigger_mode="manual",
        ),
    )


def get_binding(
    session: Session,
    binding_id: int,
) -> GoalIntegrationBinding:
    binding = session.get(GoalIntegrationBinding, binding_id)
    if binding is None:
        raise BindingNotFound("Goal integration not found")
    return binding


def list_bindings(
    session: Session,
    goal_id: int | None = None,
) -> list[GoalIntegrationBinding]:
    statement = select(GoalIntegrationBinding)
    if goal_id is not None:
        statement = statement.where(
            GoalIntegrationBinding.goal_id == goal_id
        )
    return list(
        session.exec(
            statement.order_by(GoalIntegrationBinding.id)
        ).all()
    )


def execute_binding(
    session: Session,
    binding_id: int,
    body: BindingExecuteRequest,
):
    binding = get_binding(session, binding_id)
    if not binding.enabled:
        raise BindingError("Goal integration is disabled")
    provider = session.get(IntegrationProvider, binding.provider_id)
    operation = session.get(IntegrationOperation, binding.operation_id)
    if provider is None or operation is None:
        raise BindingNotFound("Connector operation not found")
    parameters = {
        **binding.default_parameters,
        **body.parameters,
    }
    run = executor.execute(
        session,
        ExecuteRequest(
            provider=provider.slug,
            operation=operation.operation_id,
            parameters=parameters,
            capture=MeasurementCapture(
                goal_id=binding.goal_id,
                metric=binding.metric,
                value_from=binding.value_from,
                unit=binding.unit,
                external_id_from=binding.external_id_from,
            ),
        ),
    )
    binding.last_run_at = utc_now()
    binding.updated_at = binding.last_run_at
    session.add(binding)
    session.commit()
    return run


def _window_start(goal: Goal, now: datetime) -> datetime | None:
    start = goal_period_start(goal, now)
    if start is None:
        return None
    try:
        hour, minute = (
            int(part)
            for part in (goal.reset_time or "00:00").split(":")
        )
        reset_time = time(hour, minute)
    except (TypeError, ValueError):
        reset_time = time()
    return datetime.combine(start, reset_time)


def integration_goal_aggregates(
    session: Session,
    now: datetime | None = None,
) -> tuple[dict[int, float], dict[int, str], dict[int, str]]:
    now = now or datetime.now()
    values: dict[int, float] = {}
    units: dict[int, str] = {}
    labels: dict[int, str] = {}
    bindings = session.exec(
        select(GoalIntegrationBinding).where(
            GoalIntegrationBinding.enabled.is_(True)
        )
    ).all()
    for binding in bindings:
        goal = session.get(Goal, binding.goal_id)
        provider = session.get(IntegrationProvider, binding.provider_id)
        if goal is None or provider is None:
            continue
        statement = select(GoalMeasurement).where(
            GoalMeasurement.goal_id == binding.goal_id,
            GoalMeasurement.metric == binding.metric,
            GoalMeasurement.source == provider.slug,
        )
        start = _window_start(goal, now)
        if start is not None:
            statement = statement.where(
                GoalMeasurement.observed_at >= start
            )

        if binding.aggregation == "latest":
            measurement = session.exec(
                statement.order_by(
                    GoalMeasurement.observed_at.desc(),
                    GoalMeasurement.id.desc(),
                )
            ).first()
            value = measurement.value if measurement is not None else 0.0
        elif binding.aggregation == "count":
            value = float(
                session.exec(
                    select(func.count()).select_from(
                        statement.subquery()
                    )
                ).one()
            )
        else:
            measurements = session.exec(statement).all()
            raw_values = [item.value for item in measurements]
            if binding.aggregation == "average":
                value = (
                    sum(raw_values) / len(raw_values)
                    if raw_values
                    else 0.0
                )
            else:
                value = sum(raw_values)
        values[binding.goal_id] = round(float(value), 2)
        units[binding.goal_id] = (
            "entries" if binding.aggregation == "count" else binding.unit
        )
        labels[binding.goal_id] = provider.name
    return values, units, labels
