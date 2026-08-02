import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlmodel import Session, select

from app.auto_integration.builtins import BUILTIN_CONNECTORS
from app.auto_integration.models import (
    GoalMeasurement,
    IntegrationOperation,
    IntegrationProvider,
    IntegrationRun,
    utc_now,
)
from app.auto_integration.schemas import (
    ConnectorManifest,
    MeasurementCreate,
    OperationManifest,
)
from app.budget.models import Goal


class IntegrationError(Exception):
    pass


class IntegrationNotFound(IntegrationError):
    pass


class IntegrationConflict(IntegrationError):
    pass


_PLACEHOLDER_RE = re.compile(r"{([a-zA-Z][a-zA-Z0-9_]*)}")
_OUTPUT_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_SENSITIVE_NAMES = {
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}


def _valid_query_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    return isinstance(value, list) and all(
        item is None or isinstance(item, (str, int, float, bool))
        for item in value
    )


def _reject_external_references(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref":
                raise IntegrationError(
                    "External and local JSON Schema references are not supported "
                    "in connector manifests"
                )
            _reject_external_references(child)
    elif isinstance(value, list):
        for child in value:
            _reject_external_references(child)


def _normalized_parameter_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def normalize_base_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme != "https":
        raise IntegrationError("Connector base_url must use HTTPS")
    if not parsed.hostname:
        raise IntegrationError("Connector base_url must include a hostname")
    if parsed.username or parsed.password:
        raise IntegrationError("Connector base_url cannot include credentials")
    if parsed.query or parsed.fragment:
        raise IntegrationError("Connector base_url cannot include a query or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise IntegrationError("Connector base_url has an invalid port") from exc
    if port not in (None, 443):
        raise IntegrationError("Connector base_url can only use HTTPS port 443")
    hostname = parsed.hostname.lower()
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
    ):
        raise IntegrationError(
            "Connector base_url must use a public hostname"
        )

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise IntegrationError("Connector base_url cannot use a private IP address")

    path = parsed.path.rstrip("/")
    return urlunsplit(("https", parsed.netloc.lower(), path, "", ""))


def validate_operation(operation: OperationManifest) -> None:
    path = operation.path_template
    if not path.startswith("/"):
        raise IntegrationError(
            f"{operation.operation_id}: path_template must start with /"
        )
    if any(token in path for token in ("..", "\\", "://", "?", "#")):
        raise IntegrationError(
            f"{operation.operation_id}: path_template contains an unsafe token"
        )

    placeholders = _PLACEHOLDER_RE.findall(path)
    if set(placeholders) != set(operation.path_parameters):
        raise IntegrationError(
            f"{operation.operation_id}: path_parameters must exactly match "
            "the path_template placeholders"
        )
    if len(placeholders) != len(set(placeholders)):
        raise IntegrationError(
            f"{operation.operation_id}: path placeholders must be unique"
        )
    if "{" in _PLACEHOLDER_RE.sub("", path) or "}" in _PLACEHOLDER_RE.sub("", path):
        raise IntegrationError(
            f"{operation.operation_id}: path_template contains malformed placeholders"
        )

    for schema_name, schema in (
        ("input_schema", operation.input_schema),
        ("response_schema", operation.response_schema),
    ):
        if schema is None:
            continue
        _reject_external_references(schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise IntegrationError(
                f"{operation.operation_id}: invalid {schema_name}: {exc.message}"
            ) from exc

    if operation.input_schema.get("type") != "object":
        raise IntegrationError(
            f"{operation.operation_id}: input_schema must describe an object"
        )
    properties = operation.input_schema.get("properties", {})
    required = set(operation.input_schema.get("required", []))
    if not isinstance(properties, dict):
        raise IntegrationError(
            f"{operation.operation_id}: input_schema properties must be an object"
        )
    if not set(operation.path_parameters) <= set(properties):
        raise IntegrationError(
            f"{operation.operation_id}: every path parameter needs an input schema"
        )
    if not set(operation.path_parameters) <= required:
        raise IntegrationError(
            f"{operation.operation_id}: every path parameter must be required"
        )

    parameter_names = set(properties) | set(operation.fixed_query)
    for name in parameter_names:
        normalized = _normalized_parameter_name(name)
        if any(sensitive in normalized for sensitive in _SENSITIVE_NAMES):
            raise IntegrationError(
                f"{operation.operation_id}: credentials cannot be request parameters"
            )
    if set(properties) & set(operation.fixed_query):
        raise IntegrationError(
            f"{operation.operation_id}: fixed query parameters cannot be user inputs"
        )
    if any(
        not _valid_query_value(value)
        for value in operation.fixed_query.values()
    ):
        raise IntegrationError(
            f"{operation.operation_id}: fixed query values must be scalar or arrays"
        )
    if len(json.dumps(operation.fixed_query)) > 8_192:
        raise IntegrationError(
            f"{operation.operation_id}: fixed_query is too large"
        )

    for output_key, pointer in operation.result_mapping.items():
        if not _OUTPUT_KEY_RE.fullmatch(output_key):
            raise IntegrationError(
                f"{operation.operation_id}: invalid mapped output key {output_key!r}"
            )
        if pointer and not pointer.startswith("/"):
            raise IntegrationError(
                f"{operation.operation_id}: result mappings must use JSON Pointers"
            )


def validate_manifest(manifest: ConnectorManifest) -> str:
    normalized_url = normalize_base_url(manifest.base_url)
    operation_ids = [operation.operation_id for operation in manifest.operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise IntegrationError("Connector operation IDs must be unique")
    for operation in manifest.operations:
        validate_operation(operation)
    return normalized_url


def install_connector(
    session: Session,
    manifest: ConnectorManifest,
    *,
    commit: bool = True,
) -> IntegrationProvider:
    normalized_url = validate_manifest(manifest)
    existing = session.exec(
        select(IntegrationProvider).where(
            IntegrationProvider.slug == manifest.slug
        )
    ).first()
    if existing is not None:
        raise IntegrationConflict(
            f"Connector {manifest.slug!r} is already installed"
        )

    now = utc_now()
    provider = IntegrationProvider(
        slug=manifest.slug,
        name=manifest.name,
        description=manifest.description,
        base_url=normalized_url,
        documentation_url=manifest.documentation_url,
        source_url=manifest.source_url,
        license_name=manifest.license_name,
        auth_type=manifest.auth_type,
        user_agent=manifest.user_agent,
        manifest_version=manifest.manifest_version,
        metadata_json=manifest.metadata,
        created_at=now,
        updated_at=now,
    )
    session.add(provider)
    session.flush()

    for definition in manifest.operations:
        session.add(
            IntegrationOperation(
                provider_id=provider.id,
                operation_id=definition.operation_id,
                name=definition.name,
                description=definition.description,
                method=definition.method,
                path_template=definition.path_template,
                path_parameters=definition.path_parameters,
                fixed_query=definition.fixed_query,
                input_schema=definition.input_schema,
                response_schema=definition.response_schema,
                result_mapping=definition.result_mapping,
                timeout_seconds=definition.timeout_seconds,
                max_response_bytes=definition.max_response_bytes,
                created_at=now,
                updated_at=now,
            )
        )
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(provider)
    return provider


def seed_builtin_connectors(session: Session) -> None:
    installed = set(
        session.exec(select(IntegrationProvider.slug)).all()
    )
    for manifest in BUILTIN_CONNECTORS:
        if manifest.slug not in installed:
            install_connector(session, manifest)


def list_operations(
    session: Session,
    provider_id: int,
) -> list[IntegrationOperation]:
    return list(
        session.exec(
            select(IntegrationOperation)
            .where(IntegrationOperation.provider_id == provider_id)
            .order_by(IntegrationOperation.operation_id)
        ).all()
    )


def get_connector(
    session: Session,
    slug: str,
) -> tuple[IntegrationProvider, list[IntegrationOperation]]:
    provider = session.exec(
        select(IntegrationProvider).where(IntegrationProvider.slug == slug)
    ).first()
    if provider is None:
        raise IntegrationNotFound("Connector not found")
    return provider, list_operations(session, provider.id)


def create_measurement(
    session: Session,
    body: MeasurementCreate,
) -> GoalMeasurement:
    if session.get(Goal, body.goal_id) is None:
        raise IntegrationNotFound("Goal not found")
    if body.run_id is not None:
        run = session.get(IntegrationRun, body.run_id)
        if run is None:
            raise IntegrationNotFound("Integration run not found")
        if run.goal_id is not None and run.goal_id != body.goal_id:
            raise IntegrationError("Run belongs to a different goal")
        existing_for_run = session.exec(
            select(GoalMeasurement).where(
                GoalMeasurement.run_id == body.run_id
            )
        ).first()
        if existing_for_run is not None:
            return existing_for_run

    if body.external_id is not None:
        existing = session.exec(
            select(GoalMeasurement).where(
                GoalMeasurement.goal_id == body.goal_id,
                GoalMeasurement.source == body.source,
                GoalMeasurement.external_id == body.external_id,
            )
        ).first()
        if existing is not None:
            return existing

    measurement = GoalMeasurement(
        goal_id=body.goal_id,
        run_id=body.run_id,
        metric=body.metric,
        value=body.value,
        unit=body.unit,
        observed_at=body.observed_at or utc_now(),
        source=body.source,
        external_id=body.external_id,
        raw_data=body.raw_data,
    )
    session.add(measurement)
    session.commit()
    session.refresh(measurement)
    return measurement


def list_measurements(
    session: Session,
    goal_id: int,
    metric: str | None = None,
) -> list[GoalMeasurement]:
    if session.get(Goal, goal_id) is None:
        raise IntegrationNotFound("Goal not found")
    statement = select(GoalMeasurement).where(
        GoalMeasurement.goal_id == goal_id
    )
    if metric:
        statement = statement.where(GoalMeasurement.metric == metric)
    return list(
        session.exec(
            statement.order_by(
                GoalMeasurement.observed_at,
                GoalMeasurement.id,
            )
        ).all()
    )
