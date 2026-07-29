from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OperationManifest(StrictModel):
    operation_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    method: Literal["GET"] = "GET"
    path_template: str = Field(min_length=1, max_length=500)
    path_parameters: list[str] = Field(default_factory=list, max_length=20)
    fixed_query: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )
    response_schema: dict[str, Any] | None = None
    result_mapping: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    max_response_bytes: int = Field(
        default=1_000_000,
        ge=1_024,
        le=5_000_000,
    )


class ConnectorManifest(StrictModel):
    manifest_version: Literal[1] = 1
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    base_url: str = Field(min_length=1, max_length=500)
    documentation_url: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)
    license_name: str | None = Field(default=None, max_length=120)
    auth_type: Literal["none"] = "none"
    user_agent: str | None = Field(default=None, max_length=300)
    metadata: dict[str, Any] = Field(default_factory=dict)
    operations: list[OperationManifest] = Field(min_length=1, max_length=100)


class DiscoveredParameter(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    location: Literal["path", "query"]
    schema_type: Literal["string", "integer", "number", "boolean"]
    required: bool = False
    description: str = Field(default="", max_length=500)
    min_length: int | None = Field(default=None, ge=0, le=1_000)
    max_length: int | None = Field(default=None, ge=1, le=10_000)
    minimum: float | None = None
    maximum: float | None = None
    enum: list[str] = Field(default_factory=list, max_length=50)


class DiscoveredFixedQuery(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
    value: str = Field(max_length=500)


class DiscoveredMapping(StrictModel):
    output_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    json_pointer: str = Field(max_length=500)


class DiscoveredOperation(StrictModel):
    operation_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    path_template: str = Field(min_length=1, max_length=500)
    parameters: list[DiscoveredParameter] = Field(
        default_factory=list,
        max_length=20,
    )
    fixed_query: list[DiscoveredFixedQuery] = Field(
        default_factory=list,
        max_length=20,
    )
    result_mapping: list[DiscoveredMapping] = Field(
        min_length=1,
        max_length=50,
    )


class DiscoveredConnector(StrictModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    base_url: str = Field(min_length=1, max_length=500)
    documentation_url: str = Field(min_length=1, max_length=1000)
    source_url: str = Field(min_length=1, max_length=1000)
    license_name: str = Field(min_length=1, max_length=120)
    authentication: Literal["none"]
    user_agent: str | None = Field(default=None, max_length=300)
    category: str = Field(min_length=1, max_length=80)
    operations: list[DiscoveredOperation] = Field(min_length=1, max_length=3)


class ResearchEvidence(StrictModel):
    kind: Literal["documentation", "source", "license", "terms", "other"]
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    notes: str = Field(default="", max_length=1000)


class ResearchSource(StrictModel):
    title: str = Field(default="", max_length=500)
    url: str = Field(min_length=1, max_length=2000)


class AlternativeCandidate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    documentation_url: str | None = Field(default=None, max_length=1000)
    reason_not_selected: str = Field(min_length=1, max_length=1000)


class SuggestedCapture(StrictModel):
    operation: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    value_from: str = Field(min_length=1, max_length=64)
    unit: str = Field(min_length=1, max_length=40)
    external_id_from: str | None = Field(default=None, max_length=64)


class DiscoveryDraft(StrictModel):
    recommendation_status: Literal["found", "not_found"]
    summary: str = Field(min_length=1, max_length=2000)
    fit_rationale: str = Field(default="", max_length=2000)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    connector: DiscoveredConnector | None = None
    suggested_capture: SuggestedCapture | None = None
    sources: list[ResearchEvidence] = Field(default_factory=list, max_length=20)
    alternatives: list[AlternativeCandidate] = Field(
        default_factory=list,
        max_length=5,
    )


class ProposalCreate(StrictModel):
    intent: str = Field(min_length=10, max_length=2000)
    goal_id: int | None = None
    desired_metric: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.-]{1,63}$",
    )
    desired_unit: str | None = Field(default=None, min_length=1, max_length=40)
    constraints: list[str] = Field(default_factory=list, max_length=10)


class ProposalManifestUpdate(StrictModel):
    manifest: ConnectorManifest
    note: str | None = Field(default=None, max_length=2000)


class ProposalReview(StrictModel):
    note: str | None = Field(default=None, max_length=2000)


ProposalStatus = Literal[
    "researching",
    "ready_for_review",
    "invalid",
    "no_match",
    "failed",
    "approved",
    "rejected",
]


class ProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    goal_id: int | None
    provider_id: int | None
    status: ProposalStatus
    intent: str
    desired_metric: str | None
    desired_unit: str | None
    constraints: list[str] = Field(validation_alias="constraints_json")
    draft: DiscoveryDraft | None = Field(validation_alias="draft_json")
    research_sources: list[ResearchSource] = Field(
        validation_alias="research_sources_json"
    )
    manifest: ConnectorManifest | None = Field(validation_alias="manifest_json")
    validation_errors: list[str]
    failure_reason: str | None
    review_note: str | None
    model: str | None
    model_response_id: str | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None


class ProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    slug: str
    name: str
    description: str
    base_url: str
    documentation_url: str | None
    source_url: str | None
    license_name: str | None
    auth_type: str
    enabled: bool
    manifest_version: int
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime
    updated_at: datetime


class OperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    operation_id: str
    name: str
    description: str
    method: str
    path_template: str
    path_parameters: list[str]
    fixed_query: dict[str, Any]
    input_schema: dict[str, Any]
    response_schema: dict[str, Any] | None
    result_mapping: dict[str, str]
    timeout_seconds: float
    max_response_bytes: int
    enabled: bool


class ConnectorRead(ProviderRead):
    operations: list[OperationRead]


class BindingCreate(StrictModel):
    goal_id: int
    provider: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    operation: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    unit: str = Field(min_length=1, max_length=40)
    aggregation: Literal["sum", "latest", "average", "count"] = "sum"
    value_from: str = Field(min_length=1, max_length=64)
    external_id_from: str | None = Field(default=None, max_length=64)
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    trigger_mode: Literal["manual", "scheduled", "barcode", "image"] = "manual"


class BindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    provider_id: int
    operation_id: int
    metric: str
    unit: str
    aggregation: str
    value_from: str
    external_id_from: str | None
    default_parameters: dict[str, Any]
    trigger_mode: str
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BindingExecuteRequest(StrictModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


class MeasurementCapture(StrictModel):
    goal_id: int
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    value_from: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    external_id_from: str | None = Field(default=None, max_length=120)
    observed_at: datetime | None = None


class ExecuteRequest(StrictModel):
    provider: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    operation: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    capture: MeasurementCapture | None = None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: int
    operation_id: int
    goal_id: int | None
    status: str
    request_parameters: dict[str, Any]
    response_payload: Any | None
    mapped_payload: dict[str, Any]
    http_status: int | None
    error: str | None
    duration_ms: int | None
    started_at: datetime
    completed_at: datetime | None


class MeasurementCreate(StrictModel):
    goal_id: int
    run_id: str | None = None
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    value: float
    unit: str = Field(min_length=1, max_length=40)
    observed_at: datetime | None = None
    source: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    external_id: str | None = Field(default=None, max_length=300)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class MeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    run_id: str | None
    metric: str
    value: float
    unit: str
    observed_at: datetime
    source: str
    external_id: str | None
    raw_data: dict[str, Any]
    created_at: datetime
