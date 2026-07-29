"""Persistence, deterministic compilation, and review for connector proposals."""

import ipaddress
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import ValidationError
from sqlmodel import Session, select

from app.auto_integration import researcher
from app.auto_integration.models import (
    IntegrationProposal,
    utc_now,
)
from app.auto_integration.schemas import (
    ConnectorManifest,
    DiscoveryDraft,
    OperationManifest,
    ProposalCreate,
    ProposalManifestUpdate,
    ProposalReview,
    ResearchSource,
)
from app.auto_integration.service import (
    IntegrationConflict,
    IntegrationError,
    install_connector,
    validate_manifest,
)
from app.budget.models import Goal


class ProposalError(Exception):
    pass


class ProposalNotFound(ProposalError):
    pass


class ProposalConflict(ProposalError):
    pass


REVIEWABLE_STATUS = "ready_for_review"
FINAL_STATUSES = {"approved", "rejected"}
ALL_STATUSES = {
    "researching",
    REVIEWABLE_STATUS,
    "invalid",
    "no_match",
    "failed",
    *FINAL_STATUSES,
}
_UNSAFE_LICENSE_NAMES = {"", "unknown", "none", "proprietary", "unlicensed"}


def _validate_reference_url(url: str, label: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProposalError(f"{label} must be a public HTTPS URL")
    if parsed.username or parsed.password:
        raise ProposalError(f"{label} cannot contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ProposalError(f"{label} has an invalid port") from exc
    if port not in (None, 443):
        raise ProposalError(f"{label} can only use HTTPS port 443")
    hostname = parsed.hostname.lower()
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
    ):
        raise ProposalError(f"{label} must use a public hostname")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ProposalError(f"{label} cannot use a private IP address")


def _canonical_reference(url: str) -> str:
    parsed = urlsplit(url)
    return (
        f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        f"{parsed.path.rstrip('/') or '/'}"
    )


def _parameter_schema(parameter) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": parameter.schema_type,
    }
    if parameter.description:
        schema["description"] = parameter.description
    if parameter.schema_type == "string":
        schema["minLength"] = (
            parameter.min_length
            if parameter.min_length is not None
            else 0
        )
        schema["maxLength"] = (
            parameter.max_length
            if parameter.max_length is not None
            else 500
        )
        if schema["minLength"] > schema["maxLength"]:
            raise ProposalError(
                f"Parameter {parameter.name!r} has inconsistent length limits"
            )
        if parameter.enum:
            schema["enum"] = parameter.enum
    elif parameter.schema_type in {"integer", "number"}:
        if parameter.minimum is not None:
            schema["minimum"] = parameter.minimum
        if parameter.maximum is not None:
            schema["maximum"] = parameter.maximum
        if (
            parameter.minimum is not None
            and parameter.maximum is not None
            and parameter.minimum > parameter.maximum
        ):
            raise ProposalError(
                f"Parameter {parameter.name!r} has inconsistent numeric limits"
            )
    return schema


def compile_draft(
    draft: DiscoveryDraft,
    request: ProposalCreate,
    research_sources: tuple[ResearchSource, ...] | None = None,
) -> ConnectorManifest:
    if draft.recommendation_status != "found" or draft.connector is None:
        raise ProposalError("The research did not identify a compatible API")
    connector = draft.connector
    if connector.license_name.strip().lower() in _UNSAFE_LICENSE_NAMES:
        raise ProposalError("The proposed API needs an identifiable open-source license")

    _validate_reference_url(connector.documentation_url, "documentation_url")
    _validate_reference_url(connector.source_url, "source_url")
    evidence_kinds = {source.kind for source in draft.sources}
    missing_evidence = {"documentation", "source", "license"} - evidence_kinds
    if missing_evidence:
        raise ProposalError(
            "Research evidence is missing: " + ", ".join(sorted(missing_evidence))
        )
    for source in draft.sources:
        _validate_reference_url(source.url, f"{source.kind} evidence URL")
    for alternative in draft.alternatives:
        if alternative.documentation_url:
            _validate_reference_url(
                alternative.documentation_url,
                "alternative documentation URL",
            )

    if research_sources is not None:
        searched_urls = {
            _canonical_reference(source.url)
            for source in research_sources
        }
        if not searched_urls:
            raise ProposalError(
                "The agent did not return evidence from a web search"
            )
        for required_kind in ("documentation", "source"):
            supported = any(
                source.kind == required_kind
                and _canonical_reference(source.url) in searched_urls
                for source in draft.sources
            )
            if not supported:
                raise ProposalError(
                    f"{required_kind} evidence was not present in web-search results"
                )

    operations: list[OperationManifest] = []
    for operation in connector.operations:
        parameter_names = [parameter.name for parameter in operation.parameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise ProposalError(
                f"{operation.operation_id}: parameter names must be unique"
            )
        fixed_names = [item.name for item in operation.fixed_query]
        if len(fixed_names) != len(set(fixed_names)):
            raise ProposalError(
                f"{operation.operation_id}: fixed query names must be unique"
            )
        mapping_keys = [item.output_key for item in operation.result_mapping]
        if len(mapping_keys) != len(set(mapping_keys)):
            raise ProposalError(
                f"{operation.operation_id}: output mapping keys must be unique"
            )

        path_parameters = [
            parameter.name
            for parameter in operation.parameters
            if parameter.location == "path"
        ]
        required = [
            parameter.name
            for parameter in operation.parameters
            if parameter.required or parameter.location == "path"
        ]
        input_schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                parameter.name: _parameter_schema(parameter)
                for parameter in operation.parameters
            },
            "required": required,
            "additionalProperties": False,
        }
        operations.append(
            OperationManifest(
                operation_id=operation.operation_id,
                name=operation.name,
                description=operation.description,
                method="GET",
                path_template=operation.path_template,
                path_parameters=path_parameters,
                fixed_query={
                    item.name: item.value
                    for item in operation.fixed_query
                },
                input_schema=input_schema,
                response_schema=None,
                result_mapping={
                    item.output_key: item.json_pointer
                    for item in operation.result_mapping
                },
            )
        )

    manifest = ConnectorManifest(
        manifest_version=1,
        slug=connector.slug,
        name=connector.name,
        description=connector.description,
        base_url=connector.base_url,
        documentation_url=connector.documentation_url,
        source_url=connector.source_url,
        license_name=connector.license_name,
        auth_type="none",
        user_agent=connector.user_agent,
        metadata={
            "category": connector.category,
            "discovered_by": "anthropic-web-search",
        },
        operations=operations,
    )
    validate_manifest(manifest)

    capture = draft.suggested_capture
    if capture is not None:
        selected = next(
            (
                operation
                for operation in manifest.operations
                if operation.operation_id == capture.operation
            ),
            None,
        )
        if selected is None:
            raise ProposalError(
                "Suggested capture references an unknown operation"
            )
        mapped_keys = set(selected.result_mapping)
        if capture.value_from not in mapped_keys:
            raise ProposalError(
                "Suggested capture value_from is not a mapped output"
            )
        if (
            capture.external_id_from is not None
            and capture.external_id_from not in mapped_keys
        ):
            raise ProposalError(
                "Suggested capture external_id_from is not a mapped output"
            )
        if request.desired_metric:
            capture.metric = request.desired_metric
        if request.desired_unit:
            capture.unit = request.desired_unit
    elif request.desired_metric or request.desired_unit:
        raise ProposalError(
            "Research did not provide a measurement capture for the requested metric"
        )
    return manifest


def create_proposal(
    session: Session,
    body: ProposalCreate,
) -> IntegrationProposal:
    if body.goal_id is not None and session.get(Goal, body.goal_id) is None:
        raise ProposalNotFound("Goal not found")

    proposal = IntegrationProposal(
        id=str(uuid4()),
        goal_id=body.goal_id,
        status="researching",
        intent=body.intent,
        desired_metric=body.desired_metric,
        desired_unit=body.desired_unit,
        constraints_json=body.constraints,
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)

    try:
        result = researcher.research_connector(body)
        proposal.model = result.model
        proposal.model_response_id = result.response_id
        proposal.research_sources_json = [
            source.model_dump(mode="json")
            for source in result.sources
        ]
        if result.draft.recommendation_status == "not_found":
            proposal.status = "no_match"
        else:
            try:
                manifest = compile_draft(
                    result.draft,
                    body,
                    result.sources,
                )
            except (IntegrationError, ProposalError, ValidationError) as exc:
                proposal.status = "invalid"
                proposal.validation_errors = [str(exc)]
            else:
                proposal.manifest_json = manifest.model_dump(mode="json")
                proposal.status = REVIEWABLE_STATUS
        proposal.draft_json = result.draft.model_dump(mode="json")
    except researcher.ResearchError as exc:
        proposal.status = "failed"
        proposal.failure_reason = str(exc)

    proposal.updated_at = utc_now()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def get_proposal(session: Session, proposal_id: str) -> IntegrationProposal:
    proposal = session.get(IntegrationProposal, proposal_id)
    if proposal is None:
        raise ProposalNotFound("Integration proposal not found")
    return proposal


def list_proposals(
    session: Session,
    status: str | None = None,
) -> list[IntegrationProposal]:
    if status is not None and status not in ALL_STATUSES:
        raise ProposalError("Unknown proposal status")
    statement = select(IntegrationProposal)
    if status is not None:
        statement = statement.where(IntegrationProposal.status == status)
    return list(
        session.exec(
            statement.order_by(
                IntegrationProposal.created_at.desc(),
                IntegrationProposal.id,
            )
        ).all()
    )


def update_manifest(
    session: Session,
    proposal_id: str,
    body: ProposalManifestUpdate,
) -> IntegrationProposal:
    proposal = get_proposal(session, proposal_id)
    if proposal.status in FINAL_STATUSES:
        raise ProposalConflict("A reviewed proposal cannot be edited")
    validate_manifest(body.manifest)
    proposal.manifest_json = body.manifest.model_dump(mode="json")
    proposal.status = REVIEWABLE_STATUS
    proposal.validation_errors = []
    proposal.failure_reason = None
    proposal.review_note = body.note
    proposal.updated_at = utc_now()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def approve_proposal(
    session: Session,
    proposal_id: str,
    body: ProposalReview,
) -> IntegrationProposal:
    proposal = get_proposal(session, proposal_id)
    if proposal.status != REVIEWABLE_STATUS or proposal.manifest_json is None:
        raise ProposalConflict("Only a ready-for-review proposal can be approved")
    manifest = ConnectorManifest.model_validate(proposal.manifest_json)
    validate_manifest(manifest)
    try:
        provider = install_connector(session, manifest, commit=False)
    except (IntegrationConflict, IntegrationError):
        session.rollback()
        raise

    proposal.provider_id = provider.id
    proposal.status = "approved"
    proposal.review_note = body.note
    proposal.reviewed_at = utc_now()
    proposal.updated_at = proposal.reviewed_at
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def reject_proposal(
    session: Session,
    proposal_id: str,
    body: ProposalReview,
) -> IntegrationProposal:
    proposal = get_proposal(session, proposal_id)
    if proposal.status in FINAL_STATUSES:
        raise ProposalConflict("Proposal has already been reviewed")
    proposal.status = "rejected"
    proposal.review_note = body.note
    proposal.reviewed_at = utc_now()
    proposal.updated_at = proposal.reviewed_at
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal
