def test_sync_all_accounts_returns_job_id_instead_of_500(non_admin_client):
    """Regression test: POST /accounts/sync-all was declared as a plain `def` endpoint, so
    FastAPI dispatched it in a worker thread with no running asyncio event loop. Inside it,
    start_job() calls asyncio.create_task(), which raised "RuntimeError: no running event
    loop" - an unhandled exception that surfaced to the frontend as a bare, non-JSON 500
    (rendered as "Gmail sync: Gmail sync failed"). Making the endpoint `async def` runs it on
    the event loop like every other start_job() caller.
    """
    response = non_admin_client.post("/api/integrations/gmail/accounts/sync-all")
    assert response.status_code == 200
    body = response.json()
    assert body["queued"] is True
    assert body["job_id"]
