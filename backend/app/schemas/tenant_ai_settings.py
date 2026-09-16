from typing import Literal

from pydantic import BaseModel

PlannerMode = Literal["off", "manual", "auto-draft", "auto-send"]
ExecutorMode = Literal["manual", "autonomous"]


class TenantAiSettingsRead(BaseModel):
    tenant_id: int
    available_template_ids: list[int]
    default_email_template_id: int | None = None
    default_whatsapp_template_id: int | None = None
    auto_draft_email: bool
    auto_draft_whatsapp: bool
    auto_send_email: bool
    auto_send_whatsapp: bool
    planner_mode: PlannerMode = "off"
    planner_profile_id: int | None = None
    checker_profile_id: int | None = None
    drafter_profile_id: int | None = None
    # Independent of planner_mode - whether the debounced tenant-brain writer runs for this tenant.
    brain_writer_enabled: bool = False
    brain_writer_profile_id: int | None = None
    # Independent of planner_mode and brain_writer_enabled - whether the debounced action-writer
    # agent runs for this tenant.
    action_writer_enabled: bool = False
    action_writer_profile_id: int | None = None
    # When on (default), a Beds24 booking webhook registers brain/action-writer triggers for this
    # tenant (still gated on the two enables above). Default true, unlike the other AI toggles.
    webhook_auto_run_enabled: bool = True
    # Independent of the raw planner/checker draft pipeline - whether the formatter stage should
    # create channel-specific rich output for approved drafts.
    formatter_enabled: bool = False
    formatter_profile_id: int | None = None
    # The sales-manager profile the planner uses when it requests a quotation.
    sales_manager_profile_id: int | None = None
    # The executor profile that validates/applies a prepared Beds24 write.
    executor_profile_id: int | None = None
    # None means "use AdminSettings.executor_default_mode" (ships "manual").
    executor_mode: ExecutorMode | None = None


class TenantAiSettingsUpdate(BaseModel):
    available_template_ids: list[int] = []
    default_email_template_id: int | None = None
    default_whatsapp_template_id: int | None = None
    auto_draft_email: bool = False
    auto_draft_whatsapp: bool = False
    auto_send_email: bool = False
    auto_send_whatsapp: bool = False
    planner_mode: PlannerMode = "off"
    planner_profile_id: int | None = None
    checker_profile_id: int | None = None
    drafter_profile_id: int | None = None
    brain_writer_enabled: bool = False
    brain_writer_profile_id: int | None = None
    action_writer_enabled: bool = False
    action_writer_profile_id: int | None = None
    webhook_auto_run_enabled: bool = True
    formatter_enabled: bool = False
    formatter_profile_id: int | None = None
    sales_manager_profile_id: int | None = None
    executor_profile_id: int | None = None
    executor_mode: ExecutorMode | None = None


class BulkTenantAiTemplateAssignment(BaseModel):
    tenant_ids: list[int]
    template_ids: list[int]
    action: Literal["add", "remove"]


class BulkTenantAiTemplateAssignmentResult(BaseModel):
    tenants_affected: int
    links_added: int
    links_removed: int


class BulkTenantPlannerModeAssignment(BaseModel):
    tenant_ids: list[int]
    planner_mode: PlannerMode


class BulkTenantPlannerModeAssignmentResult(BaseModel):
    tenants_affected: int


class BulkTenantBrainWriterAssignment(BaseModel):
    tenant_ids: list[int]
    brain_writer_enabled: bool


class BulkTenantBrainWriterAssignmentResult(BaseModel):
    tenants_affected: int


class BulkTenantActionWriterAssignment(BaseModel):
    tenant_ids: list[int]
    action_writer_enabled: bool


class BulkTenantActionWriterAssignmentResult(BaseModel):
    tenants_affected: int


class BulkTenantFormatterAssignment(BaseModel):
    tenant_ids: list[int]
    formatter_enabled: bool


class BulkTenantFormatterAssignmentResult(BaseModel):
    tenants_affected: int
