from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auto_integration import bindings, executor, proposals
from app.auto_integration.models import IntegrationProvider, IntegrationRun
from app.auto_integration.schemas import (
    ConnectorManifest,
    ConnectorRead,
    BindingCreate,
    BindingExecuteRequest,
    BindingRead,
    ExecuteRequest,
    MeasurementCreate,
    MeasurementRead,
    OperationRead,
    ProposalCreate,
    ProposalManifestUpdate,
    ProposalRead,
    ProposalReview,
    ProviderRead,
    RunRead,
)
from app.auto_integration.service import (
    IntegrationConflict,
    IntegrationError,
    IntegrationNotFound,
    create_measurement,
    get_connector,
    install_connector,
    list_measurements,
    list_operations,
)
from app.budget.db import get_session


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _connector_read(
    provider: IntegrationProvider,
    operations,
) -> ConnectorRead:
    return ConnectorRead(
        **ProviderRead.model_validate(provider).model_dump(),
        operations=[
            OperationRead.model_validate(operation)
            for operation in operations
        ],
    )


@router.get("/connectors", response_model=list[ProviderRead])
def connectors(session: Session = Depends(get_session)):
    return session.exec(
        select(IntegrationProvider).order_by(IntegrationProvider.name)
    ).all()


@router.get("/connectors/{slug}", response_model=ConnectorRead)
def connector(slug: str, session: Session = Depends(get_session)):
    try:
        provider, operations = get_connector(session, slug)
    except IntegrationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _connector_read(provider, operations)


@router.post("/connectors", response_model=ConnectorRead, status_code=201)
def add_connector(
    body: ConnectorManifest,
    session: Session = Depends(get_session),
):
    try:
        provider = install_connector(session, body)
    except IntegrationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _connector_read(
        provider,
        list_operations(session, provider.id),
    )


@router.get("/proposals", response_model=list[ProposalRead])
def integration_proposals(
    status: str | None = None,
    session: Session = Depends(get_session),
):
    try:
        return proposals.list_proposals(session, status)
    except proposals.ProposalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/proposals", response_model=ProposalRead, status_code=201)
def discover_integration(
    body: ProposalCreate,
    session: Session = Depends(get_session),
):
    try:
        return proposals.create_proposal(session, body)
    except proposals.ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/proposals/{proposal_id}", response_model=ProposalRead)
def integration_proposal(
    proposal_id: str,
    session: Session = Depends(get_session),
):
    try:
        return proposals.get_proposal(session, proposal_id)
    except proposals.ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/proposals/{proposal_id}/manifest", response_model=ProposalRead)
def edit_proposal_manifest(
    proposal_id: str,
    body: ProposalManifestUpdate,
    session: Session = Depends(get_session),
):
    try:
        return proposals.update_manifest(session, proposal_id, body)
    except proposals.ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except proposals.ProposalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (proposals.ProposalError, IntegrationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalRead)
def approve_integration_proposal(
    proposal_id: str,
    body: ProposalReview,
    session: Session = Depends(get_session),
):
    try:
        return proposals.approve_proposal(session, proposal_id, body)
    except proposals.ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (proposals.ProposalConflict, IntegrationConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (proposals.ProposalError, IntegrationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalRead)
def reject_integration_proposal(
    proposal_id: str,
    body: ProposalReview,
    session: Session = Depends(get_session),
):
    try:
        return proposals.reject_proposal(session, proposal_id, body)
    except proposals.ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except proposals.ProposalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/bindings", response_model=list[BindingRead])
def goal_integration_bindings(
    goal_id: int | None = None,
    session: Session = Depends(get_session),
):
    return bindings.list_bindings(session, goal_id)


@router.post("/bindings", response_model=BindingRead, status_code=201)
def add_goal_integration_binding(
    body: BindingCreate,
    session: Session = Depends(get_session),
):
    try:
        return bindings.create_binding(session, body)
    except bindings.BindingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except bindings.BindingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except bindings.BindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/proposals/{proposal_id}/binding",
    response_model=BindingRead,
    status_code=201,
)
def bind_approved_proposal(
    proposal_id: str,
    session: Session = Depends(get_session),
):
    try:
        return bindings.create_binding_from_proposal(session, proposal_id)
    except bindings.BindingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except bindings.BindingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except bindings.BindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/bindings/{binding_id}/execute", response_model=RunRead)
def execute_goal_integration(
    binding_id: int,
    body: BindingExecuteRequest,
    session: Session = Depends(get_session),
):
    try:
        return bindings.execute_binding(session, binding_id, body)
    except bindings.BindingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except executor.InvalidExecutionParameters as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except executor.UpstreamExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except (bindings.BindingError, executor.ExecutionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/execute", response_model=RunRead)
def execute_connector(
    body: ExecuteRequest,
    session: Session = Depends(get_session),
):
    try:
        return executor.execute(session, body)
    except executor.ExecutionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except executor.InvalidExecutionParameters as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except executor.UpstreamExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except executor.ExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs/{run_id}", response_model=RunRead)
def integration_run(
    run_id: str,
    session: Session = Depends(get_session),
):
    run = session.get(IntegrationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Integration run not found")
    return run


@router.post("/measurements", response_model=MeasurementRead, status_code=201)
def add_measurement(
    body: MeasurementCreate,
    session: Session = Depends(get_session),
):
    try:
        return create_measurement(session, body)
    except IntegrationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/goals/{goal_id}/measurements",
    response_model=list[MeasurementRead],
)
def goal_measurements(
    goal_id: int,
    metric: str | None = None,
    session: Session = Depends(get_session),
):
    try:
        return list_measurements(session, goal_id, metric)
    except IntegrationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
