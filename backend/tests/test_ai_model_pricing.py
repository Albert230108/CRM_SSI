from datetime import datetime, timedelta, timezone

from app.models.ai_agent_run import AiAgentRun, AiAgentRunStep
from app.models.ai_model_pricing import AiModelPricing
from app.models.tenant import Tenant


def _create_run(db_session, tenant, *, created_at, model, prompt_tokens, output_tokens):
    run = AiAgentRun(
        tenant_id=tenant.id,
        channel="email",
        mode="manual",
        status="completed",
        attempts=1,
        total_prompt_tokens=prompt_tokens,
        total_output_tokens=output_tokens,
        duration_ms=1234,
        created_at=created_at,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        AiAgentRunStep(
            run_id=run.id,
            step_index=0,
            stage="planner",
            model=model,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            created_at=created_at,
        )
    )
    db_session.flush()
    return run


def test_ai_model_pricing_crud_and_stats(non_admin_client, client, db_session):
    tenant = Tenant(name="Pricing tenant", booking_id="B-pricing-1")
    db_session.add(tenant)
    db_session.flush()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    previous_month = start_of_month - timedelta(days=1)

    _create_run(db_session, tenant, created_at=now, model="gemini-2.5-flash", prompt_tokens=100, output_tokens=20)
    _create_run(db_session, tenant, created_at=now, model="gemini-zero", prompt_tokens=0, output_tokens=0)
    _create_run(
        db_session,
        tenant,
        created_at=start_of_month + timedelta(days=2),
        model="gemini-2.5-pro",
        prompt_tokens=50,
        output_tokens=30,
    )
    _create_run(
        db_session,
        tenant,
        created_at=previous_month.replace(day=previous_month.day, hour=12, minute=0, second=0, microsecond=0),
        model="gemini-2.5-nano",
        prompt_tokens=25,
        output_tokens=5,
    )
    db_session.commit()

    for model_name in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-nano"):
        response = client.put(
            "/api/ai-model-pricing",
            json={
                "model": model_name,
                "input_cost_per_million_tokens": 0.3,
                "output_cost_per_million_tokens": 1.2,
            },
        )
        assert response.status_code == 200

    stats_response = non_admin_client.get("/api/ai-agent-runs/stats", params={"period": "all"})
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert stats["period"] == "all"
    assert stats["total_runs"] == 4
    assert stats["total_prompt_tokens"] == 175
    assert stats["total_output_tokens"] == 55
    assert stats["total_tokens"] == 230
    assert {row["model"] for row in stats["by_model"]} == {
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-nano",
    }
    assert all(row["model"] != "gemini-zero" for row in stats["by_model"])

    today_stats = non_admin_client.get("/api/ai-agent-runs/stats", params={"period": "today"}).json()
    assert today_stats["period"] == "today"
    assert today_stats["total_runs"] == 2
    assert {row["model"] for row in today_stats["by_model"]} == {"gemini-2.5-flash"}
    assert today_stats["total_prompt_tokens"] == 100
    assert today_stats["total_output_tokens"] == 20

    month_stats = non_admin_client.get("/api/ai-agent-runs/stats", params={"period": "month"}).json()
    assert month_stats["period"] == "month"
    assert month_stats["total_runs"] == 3
    assert {row["model"] for row in month_stats["by_model"]} == {"gemini-2.5-flash", "gemini-2.5-pro"}
    assert month_stats["total_prompt_tokens"] == 150
    assert month_stats["total_output_tokens"] == 50

    create_response = client.put(
        "/api/ai-model-pricing",
        json={
            "model": "gemini-2.5-flash",
            "input_cost_per_million_tokens": 0.3,
            "output_cost_per_million_tokens": 1.2,
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["model"] == "gemini-2.5-flash"

    pricing_rows = non_admin_client.get("/api/ai-model-pricing")
    assert pricing_rows.status_code == 200
    assert [row["model"] for row in pricing_rows.json()["items"]] == ["gemini-2.5-flash", "gemini-2.5-nano", "gemini-2.5-pro"]

    stats_response = non_admin_client.get("/api/ai-agent-runs/stats", params={"period": "all"})
    assert stats_response.status_code == 200
    stats = stats_response.json()
    flash_row = next(row for row in stats["by_model"] if row["model"] == "gemini-2.5-flash")
    pro_row = next(row for row in stats["by_model"] if row["model"] == "gemini-2.5-pro")
    nano_row = next(row for row in stats["by_model"] if row["model"] == "gemini-2.5-nano")
    assert round(flash_row["input_cost"], 6) == 0.00003
    assert round(flash_row["output_cost"], 6) == 0.000024
    assert round(flash_row["total_cost"], 6) == 0.000054
    assert round(pro_row["total_cost"], 6) == 0.000051
    assert round(nano_row["total_cost"], 6) == 0.000013
    assert round(stats["total_cost"], 6) == 0.000119
    assert stats["any_pricing_missing"] is False

    delete_response = client.delete(f"/api/ai-model-pricing/{create_response.json()['id']}")
    assert delete_response.status_code == 204
    db_session.expire_all()
    assert db_session.query(AiModelPricing).count() == 2
