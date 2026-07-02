from __future__ import annotations

import os


def get_public_frontend_base_url() -> str:
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
