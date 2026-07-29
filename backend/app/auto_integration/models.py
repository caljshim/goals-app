from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Column, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return naive UTC for the app's existing timestamp columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class IntegrationProposal(SQLModel, table=True):
    __tablename__ = "integration_proposal"

    id: str = Field(primary_key=True)
    goal_id: Optional[int] = Field(default=None, foreign_key="goal.id", index=True)
    provider_id: Optional[int] = Field(
        default=None,
        foreign_key="integration_provider.id",
        index=True,
    )
    status: str = Field(default="researching", index=True)
    intent: str = Field(sa_column=Column(Text, nullable=False))
    desired_metric: Optional[str] = None
    desired_unit: Optional[str] = None
    constraints_json: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False),
    )
    draft_json: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    research_sources_json: list[dict[str, str]] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False),
    )
    manifest_json: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False),
    )
    failure_reason: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    review_note: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    model: Optional[str] = None
    model_response_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)
    reviewed_at: Optional[datetime] = None


class IntegrationProvider(SQLModel, table=True):
    __tablename__ = "integration_provider"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    description: str = ""
    base_url: str
    documentation_url: Optional[str] = None
    source_url: Optional[str] = None
    license_name: Optional[str] = None
    auth_type: str = "none"
    user_agent: Optional[str] = None
    enabled: bool = Field(default=True, index=True)
    manifest_version: int = 1
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IntegrationOperation(SQLModel, table=True):
    __tablename__ = "integration_operation"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "operation_id",
            name="uq_integration_operation_provider_operation",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="integration_provider.id", index=True)
    operation_id: str
    name: str
    description: str = ""
    method: str = "GET"
    path_template: str
    path_parameters: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False),
    )
    fixed_query: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    response_schema: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    result_mapping: dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    timeout_seconds: float = 10.0
    max_response_bytes: int = 1_000_000
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GoalIntegrationBinding(SQLModel, table=True):
    __tablename__ = "goal_integration_binding"

    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(
        foreign_key="goal.id",
        index=True,
        unique=True,
    )
    provider_id: int = Field(
        foreign_key="integration_provider.id",
        index=True,
    )
    operation_id: int = Field(
        foreign_key="integration_operation.id",
        index=True,
    )
    metric: str = Field(index=True)
    unit: str
    aggregation: str = "sum"
    value_from: str
    external_id_from: Optional[str] = None
    default_parameters: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    trigger_mode: str = "manual"
    enabled: bool = Field(default=True, index=True)
    last_run_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IntegrationRun(SQLModel, table=True):
    __tablename__ = "integration_run"

    id: str = Field(primary_key=True)
    provider_id: int = Field(foreign_key="integration_provider.id", index=True)
    operation_id: int = Field(foreign_key="integration_operation.id", index=True)
    goal_id: Optional[int] = Field(default=None, foreign_key="goal.id", index=True)
    status: str = Field(default="running", index=True)
    request_parameters: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    response_payload: Optional[Any] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    mapped_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    http_status: Optional[int] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    started_at: datetime = Field(default_factory=utc_now, index=True)
    completed_at: Optional[datetime] = None


class GoalMeasurement(SQLModel, table=True):
    __tablename__ = "goal_measurement"
    __table_args__ = (
        UniqueConstraint(
            "goal_id",
            "source",
            "external_id",
            name="uq_goal_measurement_external",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    run_id: Optional[str] = Field(
        default=None,
        foreign_key="integration_run.id",
        index=True,
        unique=True,
    )
    metric: str = Field(index=True)
    value: float
    unit: str
    observed_at: datetime = Field(default_factory=utc_now, index=True)
    source: str = Field(index=True)
    external_id: Optional[str] = None
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)
