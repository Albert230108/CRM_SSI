import os


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment")
    return value


# Shared secret used to verify the scoped handoff JWT minted by the CRM backend.
# Must match QUOTATION_TOKEN_SECRET on the CRM backend.
QUOTATION_TOKEN_SECRET = _require_env("QUOTATION_TOKEN_SECRET")

# Base URL of the CRM backend this service calls back into for booking data and
# Beds24 reads/writes (e.g. http://backend:8000 inside the docker network).
CRM_BACKEND_URL = _require_env("CRM_BACKEND_URL").rstrip("/")

# Path (inside this container) to the mounted Tenants/ folder tree, used for
# writing generated PDFs into the same per-tenant folder structure the desktop
# app already uses.
TENANT_FILES_ROOT = _require_env("TENANT_FILES_ROOT")

# Comma-separated list of allowed CORS origins for local/dev use. In production,
# the frontend and backend are served same-origin behind nginx, so this is
# typically empty/unused.
CORS_ORIGINS = [origin.strip() for origin in os.getenv("QUOTATION_CORS_ORIGINS", "").split(",") if origin.strip()]
