"""Export/import of hand-configured, non-secret CRM settings.

This is a full "Export all / Import" backup for the config tables an operator builds up by hand
(AI agent profiles, reply templates, the Brain, admin defaults, etc.) - NOT tenant/booking/
communication data, and never secrets. It exists so a live migration of hand-written configuration
(see the Agent Instructions grid work) can be undone if something goes wrong.

Two dataset shapes:
- "global" datasets (shared config with no natural owner) support a real REPLACE: on import,
  rows absent from the file are deleted and the file's rows are written back with their original
  ids, so the table ends up byte-for-byte equal to the file. This is what the round-trip
  acceptance test (export -> edit -> import replace -> diff) exercises.
- "scoped" datasets (rows that belong to a tenant or user, which is data, not config) are always
  merged by a natural key instead: never delete an existing row, upsert by lookup instead of by
  raw id (ids are per-environment and cannot be trusted to mean the same row across deployments),
  and skip any row whose owner isn't present in the destination, reporting the skip.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Column
from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings
from app.models.ai_agent_profile import AiAgentProfile
from app.models.ai_model_pricing import AiModelPricing
from app.models.ai_reply_template import AiReplyTemplate, AiReplyTemplateBrainSection
from app.models.brain_field_definition import BrainFieldDefinition
from app.models.brain_section import BrainSection
from app.models.bulk_planner_schedule import BulkPlannerSchedule
from app.models.email_template import EmailTemplate
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_ai_template_link import TenantAiTemplateLink
from app.models.user import User
from app.models.working_memory_rule import WorkingMemoryRule

SCHEMA_VERSION = 1


class SettingsBackupError(Exception):
    """A malformed or incompatible backup file - always safe to surface to the caller as-is."""


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    model: type
    scope: str = "global"  # "global" | "scoped"
    excluded_fields: frozenset[str] = field(default_factory=frozenset)
    # "scoped" only: identifies an existing row to update instead of inserting a duplicate.
    natural_key: tuple[str, ...] = ("id",)
    # "scoped" only: the FK column (and the model it must resolve against) that must already
    # exist in the destination, or the row is skipped rather than inserted with a dangling ref.
    owner_field: str | None = None
    owner_model: type | None = None


# Declared in dependency order (a row here may reference an earlier dataset's row by id) - the
# apply pass walks this list forwards for upserts and backwards for "replace" deletes, so a
# referenced parent row is always written before, and removed after, anything pointing at it.
DATASETS: list[DatasetSpec] = [
    DatasetSpec(
        key="users",
        model=User,
        scope="scoped",
        # password_hash is a credential. default_gmail_account_id points at gmail_accounts, which
        # this backup does not export (credential-bearing) or reason about across environments -
        # carrying a raw id across would leave a dangling/wrong reference.
        excluded_fields=frozenset({"password_hash", "default_gmail_account_id"}),
        natural_key=("email",),
    ),
    DatasetSpec(key="ai_model_pricing", model=AiModelPricing),
    DatasetSpec(key="brain_sections", model=BrainSection),
    DatasetSpec(key="brain_field_definitions", model=BrainFieldDefinition),
    DatasetSpec(key="ai_reply_templates", model=AiReplyTemplate),
    DatasetSpec(key="ai_reply_template_brain_sections", model=AiReplyTemplateBrainSection),
    DatasetSpec(key="ai_agent_profiles", model=AiAgentProfile),
    DatasetSpec(key="bulk_planner_schedules", model=BulkPlannerSchedule),
    DatasetSpec(
        key="admin_settings",
        model=AdminSettings,
        # A live, decrypt-only-with-this-deployment's-key Microsoft Graph refresh token. Even the
        # ciphertext must not leave this environment.
        excluded_fields=frozenset({"onedrive_refresh_token_encrypted"}),
    ),
    DatasetSpec(key="working_memory_rules", model=WorkingMemoryRule),
    DatasetSpec(
        key="tenant_ai_settings",
        model=TenantAiSettings,
        scope="scoped",
        natural_key=("tenant_id",),
        owner_field="tenant_id",
        owner_model=Tenant,
    ),
    DatasetSpec(
        key="tenant_ai_template_links",
        model=TenantAiTemplateLink,
        scope="scoped",
        natural_key=("tenant_id", "template_id"),
        owner_field="tenant_id",
        owner_model=Tenant,
    ),
    DatasetSpec(
        key="email_templates",
        model=EmailTemplate,
        scope="scoped",
        natural_key=("user_id", "name"),
        owner_field="user_id",
        owner_model=User,
    ),
]

_DATASETS_BY_KEY = {spec.key: spec for spec in DATASETS}


@dataclass
class DatasetResult:
    key: str
    replaced: int = 0
    added: int = 0
    removed: int = 0
    skipped: int = 0
    skip_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "replaced": self.replaced,
            "added": self.added,
            "removed": self.removed,
            "skipped": self.skipped,
            "skipReasons": self.skip_reasons,
        }


def _columns(spec: DatasetSpec) -> list[str]:
    return [col.key for col in spec.model.__table__.columns if col.key not in spec.excluded_fields]


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _deserialize_value(column: Column, value: Any) -> Any:
    if value is None:
        return None
    try:
        py_type = column.type.python_type
    except NotImplementedError:
        return value
    if py_type is datetime:
        return datetime.fromisoformat(value)
    if py_type is time:
        return time.fromisoformat(value)
    if py_type is date:
        return date.fromisoformat(value)
    if py_type is Decimal:
        return Decimal(str(value))
    return value


def _serialize_row(row: Any, columns: list[str]) -> dict[str, Any]:
    return {name: _serialize_value(getattr(row, name)) for name in columns}


def _column_default(column: Column) -> Any:
    """The model-level default for a column absent from an older export (a column added by a
    later migration than the one the file was taken under). Only used when the key is missing
    entirely - a key explicitly present as null is passed through as null."""
    if column.default is None:
        return None
    arg = column.default.arg
    if not callable(arg):
        return arg
    # SQLAlchemy wraps a plain callable default (e.g. `default=list`) to accept an execution
    # context, which the caller here has none of.
    return arg(None)


def _apply_row_columns(obj: Any, spec: DatasetSpec, row: dict[str, Any], columns: list[str], *, is_new: bool) -> None:
    """Writes one row's columns onto `obj`.

    A column absent from the row (an older export, taken before a later migration added it) uses
    the model default for a brand-new row, or is left untouched on a row that already exists -
    re-importing a pre-migration backup must not blank out a column that backup never captured.
    """
    for name in columns:
        if name == "id":
            continue
        column = spec.model.__table__.columns[name]
        if name in row:
            setattr(obj, name, _deserialize_value(column, row[name]))
        elif is_new:
            setattr(obj, name, _column_default(column))


def _get_app_version() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def export_settings(db: Session) -> dict[str, Any]:
    data: dict[str, list[dict[str, Any]]] = {}
    excluded_fields: dict[str, list[str]] = {}
    for spec in DATASETS:
        columns = _columns(spec)
        rows = db.query(spec.model).order_by(spec.model.id).all()
        data[spec.key] = [_serialize_row(row, columns) for row in rows]
        if spec.excluded_fields:
            excluded_fields[spec.key] = sorted(spec.excluded_fields)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "appVersion": _get_app_version(),
        "excludedFields": excluded_fields,
        "data": data,
    }


def validate_backup_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise SettingsBackupError("File is not a recognized settings backup.")
    version = payload.get("schemaVersion")
    if not isinstance(version, int):
        raise SettingsBackupError("File is not a recognized settings backup (missing schemaVersion).")
    if version > SCHEMA_VERSION:
        raise SettingsBackupError(
            f"This backup was made with a newer format (schema {version}) than this server supports "
            f"(schema {SCHEMA_VERSION}). Upgrade the app before importing it."
        )
    if not isinstance(payload.get("data"), dict):
        raise SettingsBackupError("Malformed backup file: 'data' must be an object.")


def _find_by_natural_key(db: Session, spec: DatasetSpec, row: dict[str, Any]) -> Any | None:
    query = db.query(spec.model)
    for key in spec.natural_key:
        query = query.filter(getattr(spec.model, key) == row.get(key))
    return query.first()


def _plan_global(db: Session, spec: DatasetSpec, rows: list[dict[str, Any]]) -> DatasetResult:
    exported_ids = {row["id"] for row in rows}
    existing_ids = {row_id for (row_id,) in db.query(spec.model.id).all()}
    return DatasetResult(
        key=spec.key,
        replaced=len(exported_ids & existing_ids),
        added=len(exported_ids - existing_ids),
        removed=len(existing_ids - exported_ids),
    )


def _plan_scoped(db: Session, spec: DatasetSpec, rows: list[dict[str, Any]]) -> DatasetResult:
    owner_ids: set[Any] | None = None
    if spec.owner_field and spec.owner_model is not None:
        owner_ids = {row_id for (row_id,) in db.query(spec.owner_model.id).all()}
    result = DatasetResult(key=spec.key)
    for row in rows:
        if owner_ids is not None:
            owner_value = row.get(spec.owner_field)
            if owner_value not in owner_ids:
                result.skipped += 1
                if len(result.skip_reasons) < 5:
                    result.skip_reasons.append(
                        f"{spec.owner_field}={owner_value!r} has no matching {spec.owner_model.__tablename__} row"
                    )
                continue
        if _find_by_natural_key(db, spec, row) is not None:
            result.replaced += 1
        else:
            result.added += 1
    return result


def preview_import(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload["data"]
    plan: dict[str, Any] = {}
    for spec in DATASETS:
        rows = data.get(spec.key, [])
        outcome = _plan_scoped(db, spec, rows) if spec.scope == "scoped" else _plan_global(db, spec, rows)
        plan[spec.key] = outcome.as_dict()
    return plan


def _apply_global(db: Session, spec: DatasetSpec, rows: list[dict[str, Any]]) -> DatasetResult:
    """Upserts rows by id. Deletion of rows absent from `rows` (a "replace" import) is handled
    separately by `apply_import`'s phase 1, across all global datasets, before any upsert runs."""
    columns = _columns(spec)
    result = DatasetResult(key=spec.key)
    for row in rows:
        obj = db.get(spec.model, row["id"])
        is_new = obj is None
        if is_new:
            obj = spec.model(id=row["id"])
            db.add(obj)
            result.added += 1
        else:
            result.replaced += 1
        _apply_row_columns(obj, spec, row, columns, is_new=is_new)
    db.flush()
    return result


def _apply_scoped(db: Session, spec: DatasetSpec, rows: list[dict[str, Any]]) -> DatasetResult:
    columns = _columns(spec)
    owner_ids: set[Any] | None = None
    if spec.owner_field and spec.owner_model is not None:
        owner_ids = {row_id for (row_id,) in db.query(spec.owner_model.id).all()}
    result = DatasetResult(key=spec.key)
    for row in rows:
        if owner_ids is not None:
            owner_value = row.get(spec.owner_field)
            if owner_value not in owner_ids:
                result.skipped += 1
                if len(result.skip_reasons) < 5:
                    result.skip_reasons.append(
                        f"{spec.owner_field}={owner_value!r} has no matching {spec.owner_model.__tablename__} row"
                    )
                continue
        obj = _find_by_natural_key(db, spec, row)
        is_new = obj is None
        if is_new:
            obj = spec.model()
            db.add(obj)
            result.added += 1
        else:
            result.replaced += 1
        _apply_row_columns(obj, spec, row, columns, is_new=is_new)
    db.flush()
    return result


def apply_import(db: Session, payload: dict[str, Any], mode: str) -> dict[str, Any]:
    """Applies an already-validated backup. Caller owns the transaction (commit/rollback)."""
    if mode not in ("replace", "merge"):
        raise ValueError(f"apply_import does not support mode={mode!r}")
    data = payload["data"]
    delete_extras = mode == "replace"

    # Phase 1: all deletes for global datasets, children-before-parents, so a removed parent
    # never cascades away a sibling row that the export still wants kept.
    removed_counts: dict[str, int] = {}
    if delete_extras:
        for spec in reversed(DATASETS):
            if spec.scope != "global":
                continue
            exported_ids = {row["id"] for row in data.get(spec.key, [])}
            removed = 0
            for obj in db.query(spec.model).all():
                if obj.id not in exported_ids:
                    db.delete(obj)
                    removed += 1
            removed_counts[spec.key] = removed
        db.flush()

    # Phase 2: upserts, parents-before-children.
    results: dict[str, Any] = {}
    for spec in DATASETS:
        rows = data.get(spec.key, [])
        if spec.scope == "scoped":
            outcome = _apply_scoped(db, spec, rows)
        else:
            outcome = _apply_global(db, spec, rows)
            outcome.removed = removed_counts.get(spec.key, 0)
        results[spec.key] = outcome.as_dict()
    return results


def write_snapshot(db: Session, directory: Path) -> Path:
    """Best-effort safety net: dumps current state to disk before an import mutates anything."""
    import json

    directory.mkdir(parents=True, exist_ok=True)
    payload = export_settings(db)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot_path = directory / f"pre-import-snapshot-{timestamp}.json"
    snapshot_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return snapshot_path
