import json
import shutil

import pytest

from app.services import admin_costs as admin_costs_service


@pytest.fixture()
def temp_admin_costs(tmp_path, monkeypatch):
    """Redirect admin_costs.json to a tmp copy so tests never touch the tracked file."""
    src = admin_costs_service.ADMIN_COSTS_FILE
    dst = tmp_path / "admin_costs.json"
    shutil.copy2(src, dst)
    monkeypatch.setattr(admin_costs_service, "ADMIN_COSTS_FILE", dst)
    monkeypatch.setattr(admin_costs_service, "_admin_costs_cache", None, raising=False)
    return dst


def test_get_admin_costs(client, auth_headers, temp_admin_costs):
    response = client.get("/api/config/admin-costs", headers=auth_headers)
    assert response.status_code == 200
    assert "properties" in response.json()


def test_put_admin_costs_persists_and_busts_cache(client, auth_headers, temp_admin_costs):
    current = json.loads(temp_admin_costs.read_text())
    prop = next(iter(current["properties"]))
    current["properties"][prop]["admin_percentage"] = 12.5

    response = client.put("/api/config/admin-costs", headers=auth_headers, json=current)
    assert response.status_code == 200
    assert response.json()["properties"][prop]["admin_percentage"] == 12.5

    # File written, backup created, and the service cache reflects the new value.
    on_disk = json.loads(temp_admin_costs.read_text())
    assert on_disk["properties"][prop]["admin_percentage"] == 12.5
    assert temp_admin_costs.with_suffix(".json.backup").exists()
    assert admin_costs_service.get_admin_costs_for_property(prop)["admin_percentage"] == 12.5


def test_put_admin_costs_rejects_missing_section(client, auth_headers, temp_admin_costs):
    response = client.put("/api/config/admin-costs", headers=auth_headers, json={"nope": 1})
    assert response.status_code == 400


def test_config_unknown_name_404(client, auth_headers):
    assert client.get("/api/config/does-not-exist", headers=auth_headers).status_code == 404


def test_config_requires_token(client):
    assert client.get("/api/config/admin-costs").status_code == 401
