import ipaddress
import json
import socket
from time import perf_counter
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from sqlmodel import Session, select

from app.auto_integration.models import (
    GoalMeasurement,
    IntegrationOperation,
    IntegrationProvider,
    IntegrationRun,
    utc_now,
)
from app.auto_integration.schemas import ExecuteRequest
from app.budget.models import Goal


class ExecutionError(Exception):
    pass


class ExecutionNotFound(ExecutionError):
    pass


class InvalidExecutionParameters(ExecutionError):
    pass


class UpstreamExecutionError(ExecutionError):
    pass


def _assert_public_hostname(hostname: str, port: int = 443) -> None:
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        try:
            resolved = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ExecutionError("Connector hostname could not be resolved") from exc
        addresses = [
            ipaddress.ip_address(result[4][0])
            for result in resolved
        ]

    if not addresses or any(not address.is_global for address in addresses):
        raise ExecutionError(
            "Connector hostname resolved to a non-public network address"
        )


def _validate_parameters(
    operation: IntegrationOperation,
    parameters: dict[str, Any],
) -> None:
    try:
        Draft202012Validator(
            operation.input_schema,
            format_checker=FormatChecker(),
        ).validate(parameters)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path)
        prefix = f"{location}: " if location else ""
        raise InvalidExecutionParameters(prefix + exc.message) from exc


def _safe_query_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    return isinstance(value, list) and all(
        item is None or isinstance(item, (str, int, float, bool))
        for item in value
    )


def _build_request(
    provider: IntegrationProvider,
    operation: IntegrationOperation,
    parameters: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, str]]:
    path = operation.path_template
    for name in operation.path_parameters:
        if isinstance(parameters[name], bool) or not isinstance(
            parameters[name],
            (str, int, float),
        ):
            raise InvalidExecutionParameters(
                f"{name}: path parameters must be scalar values"
            )
        path = path.replace(
            "{" + name + "}",
            quote(str(parameters[name]), safe=""),
        )
    if "{" in path or "}" in path:
        raise ExecutionError("Connector path contains unresolved parameters")

    url = provider.base_url.rstrip("/") + path
    parsed = urlsplit(url)
    provider_host = urlsplit(provider.base_url).hostname
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExecutionError("Connector URL has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != provider_host
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise ExecutionError("Connector operation escaped its approved host")
    if len(url) > 2_048:
        raise InvalidExecutionParameters("Generated request URL is too long")

    query = dict(operation.fixed_query)
    for name, value in parameters.items():
        if name not in operation.path_parameters and value is not None:
            if not _safe_query_value(value):
                raise InvalidExecutionParameters(
                    f"{name}: query parameters must be scalar values or arrays"
                )
            query[name] = value
    rendered_url = str(httpx.URL(url, params=query))
    if len(rendered_url) > 8_192:
        raise InvalidExecutionParameters(
            "Generated request URL and query are too long"
        )

    headers = {"Accept": "application/json"}
    if provider.user_agent:
        headers["User-Agent"] = provider.user_agent
    return url, query, headers


def _read_json_response(
    response: httpx.Response,
    max_response_bytes: int,
) -> Any:
    chunks = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_response_bytes:
            raise UpstreamExecutionError(
                f"Upstream response exceeded {max_response_bytes} bytes"
            )
        chunks.append(chunk)

    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        raise UpstreamExecutionError(
            "Upstream response did not use a JSON content type"
        )
    try:
        return json.loads(
            b"".join(chunks),
            parse_constant=_invalid_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise UpstreamExecutionError(
            "Upstream returned malformed JSON"
        ) from exc


_MISSING = object()


def _invalid_json_constant(value: str):
    raise ValueError(f"Invalid JSON constant: {value}")


def _json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        return _MISSING

    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return current


def _map_response(
    payload: Any,
    mappings: dict[str, str],
) -> dict[str, Any]:
    mapped = {}
    for output_name, pointer in mappings.items():
        value = _json_pointer(payload, pointer)
        if value is not _MISSING:
            mapped[output_name] = value
    return mapped


def _capture_measurement(
    session: Session,
    request: ExecuteRequest,
    provider: IntegrationProvider,
    run: IntegrationRun,
) -> None:
    capture = request.capture
    if capture is None:
        return
    if session.get(Goal, capture.goal_id) is None:
        raise InvalidExecutionParameters("Capture goal does not exist")

    value = run.mapped_payload.get(capture.value_from, _MISSING)
    if value is _MISSING or isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise InvalidExecutionParameters(
            f"Mapped output {capture.value_from!r} is not numeric"
        )
    external_id = None
    if capture.external_id_from:
        raw_external_id = run.mapped_payload.get(capture.external_id_from)
        if raw_external_id is not None:
            external_id = str(raw_external_id)

    if external_id is not None:
        existing = session.exec(
            select(GoalMeasurement).where(
                GoalMeasurement.goal_id == capture.goal_id,
                GoalMeasurement.source == provider.slug,
                GoalMeasurement.external_id == external_id,
            )
        ).first()
        if existing is not None:
            return

    session.add(
        GoalMeasurement(
            goal_id=capture.goal_id,
            run_id=run.id,
            metric=capture.metric,
            value=float(value),
            unit=capture.unit,
            observed_at=capture.observed_at or utc_now(),
            source=provider.slug,
            external_id=external_id,
            raw_data=run.mapped_payload,
        )
    )


def execute(
    session: Session,
    request: ExecuteRequest,
    client: httpx.Client | None = None,
) -> IntegrationRun:
    provider = session.exec(
        select(IntegrationProvider).where(
            IntegrationProvider.slug == request.provider
        )
    ).first()
    if provider is None or not provider.enabled:
        raise ExecutionNotFound("Connector not found or disabled")
    operation = session.exec(
        select(IntegrationOperation).where(
            IntegrationOperation.provider_id == provider.id,
            IntegrationOperation.operation_id == request.operation,
        )
    ).first()
    if operation is None or not operation.enabled:
        raise ExecutionNotFound("Connector operation not found or disabled")
    if operation.method != "GET" or provider.auth_type != "none":
        raise ExecutionError(
            "Only unauthenticated GET connectors are supported in phase one"
        )

    _validate_parameters(operation, request.parameters)
    if request.capture and session.get(Goal, request.capture.goal_id) is None:
        raise InvalidExecutionParameters("Capture goal does not exist")
    url, query, headers = _build_request(
        provider,
        operation,
        request.parameters,
    )

    run = IntegrationRun(
        id=str(uuid4()),
        provider_id=provider.id,
        operation_id=operation.id,
        goal_id=request.capture.goal_id if request.capture else None,
        request_parameters=request.parameters,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    started = perf_counter()
    owned_client = client is None
    active_client = client or httpx.Client()
    try:
        hostname = urlsplit(url).hostname
        if hostname is None:
            raise ExecutionError("Connector URL has no hostname")
        _assert_public_hostname(hostname)

        context = active_client.stream(
            "GET",
            url,
            params=query,
            headers=headers,
            timeout=operation.timeout_seconds,
            follow_redirects=False,
        )
        with context as response:
            run.http_status = response.status_code
            payload = _read_json_response(
                response,
                operation.max_response_bytes,
            )
        run.response_payload = payload
        if not 200 <= run.http_status < 300:
            raise UpstreamExecutionError(
                f"Upstream returned HTTP {run.http_status}"
            )
        if operation.response_schema is not None:
            try:
                Draft202012Validator(operation.response_schema).validate(payload)
            except ValidationError as exc:
                raise UpstreamExecutionError(
                    f"Upstream response failed its schema: {exc.message}"
                ) from exc

        run.mapped_payload = _map_response(
            payload,
            operation.result_mapping,
        )
        _capture_measurement(session, request, provider, run)
        run.status = "completed"
        run.completed_at = utc_now()
        run.duration_ms = round((perf_counter() - started) * 1000)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run
    except Exception as exc:
        http_status = run.http_status
        response_payload = run.response_payload
        mapped_payload = run.mapped_payload
        session.rollback()
        run = session.get(IntegrationRun, run.id)
        run.http_status = http_status
        run.response_payload = response_payload
        run.mapped_payload = mapped_payload
        run.status = "failed"
        run.error = str(exc)[:1000]
        run.completed_at = utc_now()
        run.duration_ms = round((perf_counter() - started) * 1000)
        session.add(run)
        session.commit()
        if isinstance(exc, ExecutionError):
            raise
        if isinstance(exc, httpx.HTTPError):
            raise UpstreamExecutionError(
                "Connector request failed"
            ) from exc
        raise ExecutionError("Connector execution failed") from exc
    finally:
        if owned_client:
            active_client.close()
