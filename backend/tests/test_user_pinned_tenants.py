def test_get_pinned_tenants_defaults_to_none(non_admin_client):
    response = non_admin_client.get('/api/users/me/pinned-tenants')

    assert response.status_code == 200
    assert response.json() == {'tenant_ids': None}


def test_put_pinned_tenants_persists_and_reflects_on_get(non_admin_client):
    put_response = non_admin_client.put('/api/users/me/pinned-tenants', json={'tenant_ids': [1, 2, 3]})
    assert put_response.status_code == 200
    assert put_response.json() == {'tenant_ids': [1, 2, 3]}

    get_response = non_admin_client.get('/api/users/me/pinned-tenants')
    assert get_response.status_code == 200
    assert get_response.json() == {'tenant_ids': [1, 2, 3]}


def test_put_pinned_tenants_overwrites_previous_value(non_admin_client):
    non_admin_client.put('/api/users/me/pinned-tenants', json={'tenant_ids': [1, 2]})

    response = non_admin_client.put('/api/users/me/pinned-tenants', json={'tenant_ids': [3]})

    assert response.status_code == 200
    assert response.json() == {'tenant_ids': [3]}
