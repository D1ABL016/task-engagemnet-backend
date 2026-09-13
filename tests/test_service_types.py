import pytest


async def _create_service_type(http_client, headers, name="Monthly GST Compliance"):
    response = await http_client.post(
        "/api/v1/service-types", headers=headers, json={"name": name}
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_admin_creates_a_service_type_with_templates(
    http_client, admin_user, auth_headers_for
):
    headers = auth_headers_for(admin_user)
    service_type_id = await _create_service_type(http_client, headers)

    for sequence, (title, offset) in enumerate(
        [("Collect invoices", 0), ("Reconcile register", 5), ("File return", 12)], start=1
    ):
        response = await http_client.post(
            f"/api/v1/service-types/{service_type_id}/templates",
            headers=headers,
            json={"title": title, "sequence": sequence, "default_offset_days": offset},
        )
        assert response.status_code == 201

    listing = await http_client.get("/api/v1/service-types", headers=headers)
    templates = listing.json()[0]["task_templates"]
    assert [template["sequence"] for template in templates] == [1, 2, 3]
    assert [template["default_offset_days"] for template in templates] == [0, 5, 12]


@pytest.mark.asyncio
async def test_duplicate_sequence_is_rejected(http_client, admin_user, auth_headers_for):
    headers = auth_headers_for(admin_user)
    service_type_id = await _create_service_type(http_client, headers)
    template = {"title": "First", "sequence": 1, "default_offset_days": 0}

    first = await http_client.post(
        f"/api/v1/service-types/{service_type_id}/templates", headers=headers, json=template
    )
    assert first.status_code == 201

    second = await http_client.post(
        f"/api/v1/service-types/{service_type_id}/templates",
        headers=headers,
        json={"title": "Second", "sequence": 1, "default_offset_days": 3},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_negative_offset_is_rejected(http_client, admin_user, auth_headers_for):
    headers = auth_headers_for(admin_user)
    service_type_id = await _create_service_type(http_client, headers)

    response = await http_client.post(
        f"/api/v1/service-types/{service_type_id}/templates",
        headers=headers,
        json={"title": "Impossible", "sequence": 1, "default_offset_days": -1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_manager_cannot_create_a_service_type(
    http_client, manager_user, auth_headers_for
):
    response = await http_client.post(
        "/api/v1/service-types",
        headers=auth_headers_for(manager_user),
        json={"name": "Should Not Exist"},
    )
    assert response.status_code == 403
