def test_booking_group_forwards_to_crm(client, auth_headers, monkeypatch):
    captured = {}

    async def fake_get_group(booking_id, token):
        captured["booking_id"] = booking_id
        captured["token"] = token
        return {"master_id": "100", "bookings": [{"id": "100"}, {"id": "101"}]}

    import app.api.booking as booking_module

    monkeypatch.setattr(booking_module.crm_client, "get_beds24_booking_group", fake_get_group)

    response = client.get("/api/booking/group/100", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["master_id"] == "100"
    assert len(body["bookings"]) == 2
    assert captured["booking_id"] == "100"


def test_booking_group_requires_token(client):
    response = client.get("/api/booking/group/100")
    assert response.status_code == 401
