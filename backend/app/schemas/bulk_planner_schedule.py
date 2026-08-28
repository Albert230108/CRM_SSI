from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LastMessageDirection = Literal["inbound", "outbound", "either"]
RunTriggerReason = Literal["scheduled", "catch_up"]
RunStatus = Literal["running", "completed", "failed"]
RunResultOutcome = Literal["success", "skipped", "error"]


class BulkPlannerScheduleFilterFields(BaseModel):
    status_filter: list[str] = []
    last_message_within_days: int | None = Field(default=None, ge=0)
    last_message_direction: LastMessageDirection | None = None


class BulkPlannerScheduleCreate(BulkPlannerScheduleFilterFields):
    name: str = Field(min_length=1, max_length=200)
    extra_instructions: str | None = None
    enabled: bool = True
    run_time_local: time


class BulkPlannerScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    extra_instructions: str | None = None
    enabled: bool | None = None
    run_time_local: time | None = None
    status_filter: list[str] | None = None
    last_message_within_days: int | None = Field(default=None, ge=0)
    last_message_direction: LastMessageDirection | None = None


class BulkPlannerPreviewTenant(BaseModel):
    id: int
    name: str
    booking_id: str
    booking_status: str | None = None
    model_config = ConfigDict(from_attributes=True)


class BulkPlannerSchedulePreviewResponse(BaseModel):
    matched_tenant_count: int
    tenants: list[BulkPlannerPreviewTenant]


class BulkPlannerScheduleRead(BulkPlannerScheduleFilterFields):
    id: int
    name: str
    extra_instructions: str | None = None
    enabled: bool
    run_time_local: time
    last_run_at: datetime | None = None
    next_run_at: datetime
    created_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime
    last_matched_tenant_count: int | None = None
    last_run_status: RunStatus | None = None
    last_trigger_reason: RunTriggerReason | None = None
    model_config = ConfigDict(from_attributes=True)


class BulkPlannerScheduleRunRead(BaseModel):
    id: int
    schedule_id: int
    started_at: datetime
    completed_at: datetime | None = None
    trigger_reason: RunTriggerReason
    matched_tenant_count: int
    status: RunStatus
    model_config = ConfigDict(from_attributes=True)


class BulkPlannerScheduleRunListRead(BaseModel):
    total: int
    items: list[BulkPlannerScheduleRunRead]


class BulkPlannerScheduleRunResultRead(BaseModel):
    id: int
    run_id: int
    tenant_id: int
    tenant_name: str | None = None
    channel: str
    outcome: RunResultOutcome
    skip_reason: str | None = None
    error_message: str | None = None
    draft_id: int | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
