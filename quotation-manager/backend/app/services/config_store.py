"""
Read/write access to the four pricing/config JSON files under app/data/
(admin_costs, base_prices, NewCombinedPrices, discount_rules).

The desktop Quotation Manager edited these through its Price Manager / Discount
Manager / Admin Costs windows; the web port previously shipped them read-only.
This restores editability: each save writes a timestamped-in-content copy with a
`.backup` sibling first (mirroring the desktop's save_admin_costs /
save_discount_rules), then busts the in-process caches in admin_costs.py and
discount_engine.py so the next quotation build sees the new values.

NOTE (deployment): these files live inside the quotation-backend container image.
For edits to survive a redeploy they must be on a mounted volume - see the
docker-compose note. Without a volume, saved config is lost on the next deploy.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.services import admin_costs as admin_costs_service
from app.services import discount_engine


class ConfigStoreError(Exception):
    """Raised when a config file is missing, unreadable, or fails validation."""


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise ConfigStoreError(f"{path.name} not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise ConfigStoreError(f"Could not read {path.name}: {exc}") from exc


def _write_json(path: Path, data: dict) -> None:
    try:
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".backup"))
        data = dict(data)
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise ConfigStoreError(f"Could not write {path.name}: {exc}") from exc


def _bust_admin_cache() -> None:
    admin_costs_service._admin_costs_cache = None


def _bust_pricing_caches() -> None:
    discount_engine._pricing_data_cache = None
    discount_engine._base_prices_cache = None
    discount_engine._discount_rules_cache = None


# name -> (path-getter, required_top_level_key or None, cache-buster).
# The path is read from the owning module at call time (not captured at import),
# so tests can redirect the module's file constant to a tmp copy without
# touching the real git-tracked data files.
_CONFIGS: dict[str, tuple[Callable[[], Path], str | None, Callable[[], None]]] = {
    "admin-costs": (lambda: admin_costs_service.ADMIN_COSTS_FILE, "properties", _bust_admin_cache),
    "base-prices": (lambda: discount_engine.BASE_PRICES_FILE, "properties", _bust_pricing_caches),
    "prices": (lambda: discount_engine.PRICING_FILE, None, _bust_pricing_caches),
    "discount-rules": (lambda: discount_engine.DISCOUNT_RULES_FILE, "presets", _bust_pricing_caches),
}


def get_config(name: str) -> dict:
    if name not in _CONFIGS:
        raise ConfigStoreError(f"Unknown config '{name}'")
    path_getter, _required, _bust = _CONFIGS[name]
    return _read_json(path_getter())


def save_config(name: str, data: Any) -> dict:
    if name not in _CONFIGS:
        raise ConfigStoreError(f"Unknown config '{name}'")
    path_getter, required_key, bust = _CONFIGS[name]

    if not isinstance(data, dict):
        raise ConfigStoreError(f"{name} config must be a JSON object")
    if required_key is not None and required_key not in data:
        raise ConfigStoreError(f"{name} config is missing the required '{required_key}' section")

    _write_json(path_getter(), data)
    bust()
    return get_config(name)
