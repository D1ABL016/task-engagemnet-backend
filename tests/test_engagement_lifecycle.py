import pytest


async def _create_engagement(
    http_client,
    headers,
    acme_client,
    gst_service_type,
    manager_user,
    start_date="2026-08-01",
    engagement_type="recurring",
    recurrence="monthly",
):
    payload = {
        "client_id": str(acme_client.id),
        "service_type_id": str(gst_service_type.id),
        "manager_id": str(manager_user.id),
        "engagement_type": engagement_type,
        "start_date": start_date,
    }
    if engagement_type == "recurring":
        payload["recurrence"] = recurrence
    response = await http_client.post(
        "/api/v1/engagements", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_soft_deleted_engagement_disappears_from_listing_and_dashboard(
    http_client, manager_user, team_member_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    engagement = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )
    engagement_id = engagement["id"]
    task_id = engagement["tasks"][0]["id"]

    # Staff the first task so the team member's dashboard would otherwise count it.
    assign = await http_client.patch(
        f"/api/v1/tasks/{task_id}/assignment",
        headers=headers,
        json={"assignee_id": str(team_member_user.id)},
    )
    assert assign.status_code == 200

    deleted = await http_client.request(
        "DELETE",
        f"/api/v1/engagements/{engagement_id}",
        headers=headers,
        json={"reason": "Created in error"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deletion_reason"] == "Created in error"

    listing = await http_client.get("/api/v1/engagements", headers=headers)
    assert engagement_id not in [item["id"] for item in listing.json()]

    tasks = await http_client.get(
        "/api/v1/tasks", headers=headers, params={"engagement_id": engagement_id}
    )
    assert tasks.json() == []

    member_headers = auth_headers_for(team_member_user)
    dashboard = await http_client.get("/api/v1/dashboard", headers=member_headers)
    assert dashboard.json()["open_tasks"] == 0


@pytest.mark.asyncio
async def test_engagement_can_be_recreated_for_the_same_period_after_soft_delete(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    """The whole point of the partial unique index's second predicate."""
    headers = auth_headers_for(manager_user)
    engagement = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )

    delete_response = await http_client.request(
        "DELETE",
        f"/api/v1/engagements/{engagement['id']}",
        headers=headers,
        json={"reason": "Wrong client selected"},
    )
    assert delete_response.status_code == 200

    recreated = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )
    assert recreated["id"] != engagement["id"]
    assert recreated["period_start"] == engagement["period_start"]
    assert len(recreated["tasks"]) == 3


@pytest.mark.asyncio
async def test_restore_returns_engagement_and_cascade_deleted_tasks(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    engagement = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )
    engagement_id = engagement["id"]

    await http_client.request(
        "DELETE",
        f"/api/v1/engagements/{engagement_id}",
        headers=headers,
        json={"reason": "Made in error"},
    )

    restored = await http_client.post(
        f"/api/v1/engagements/{engagement_id}/restore", headers=headers
    )
    assert restored.status_code == 200
    body = restored.json()
    assert body["deleted_at"] is None
    assert len(body["tasks"]) == 3
    for task in body["tasks"]:
        assert task["due_date"] is not None


@pytest.mark.asyncio
async def test_restore_fails_with_409_when_period_now_occupied(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    original = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )

    await http_client.request(
        "DELETE",
        f"/api/v1/engagements/{original['id']}",
        headers=headers,
        json={"reason": "Made in error"},
    )

    # Someone else now legitimately occupies that same client/service/period.
    await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )

    restore = await http_client.post(
        f"/api/v1/engagements/{original['id']}/restore", headers=headers
    )
    assert restore.status_code == 409


@pytest.mark.asyncio
async def test_delete_requires_a_non_empty_reason(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    engagement = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )
    response = await http_client.request(
        "DELETE",
        f"/api/v1/engagements/{engagement['id']}",
        headers=headers,
        json={"reason": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_team_member_cannot_delete_or_patch_an_engagement(
    http_client, manager_user, team_member_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    engagement = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )
    member_headers = auth_headers_for(team_member_user)

    delete_response = await http_client.request(
        "DELETE",
        f"/api/v1/engagements/{engagement['id']}",
        headers=member_headers,
        json={"reason": "Should not be allowed"},
    )
    assert delete_response.status_code == 403

    patch_response = await http_client.patch(
        f"/api/v1/engagements/{engagement['id']}",
        headers=member_headers,
        json={"auto_renew": False},
    )
    assert patch_response.status_code == 403


@pytest.mark.asyncio
async def test_patch_updates_manager_and_auto_renew(
    http_client,
    manager_user,
    other_manager_user,
    auth_headers_for,
    acme_client,
    gst_service_type,
):
    headers = auth_headers_for(manager_user)
    engagement = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )

    response = await http_client.patch(
        f"/api/v1/engagements/{engagement['id']}",
        headers=headers,
        json={"manager_id": str(other_manager_user.id), "auto_renew": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manager_id"] == str(other_manager_user.id)
    assert body["auto_renew"] is False

    # Existing tasks' reviewer_id is untouched by the manager change.
    for task in body["tasks"]:
        assert task["reviewer_id"] == str(manager_user.id)


@pytest.mark.asyncio
async def test_patch_rejects_changing_client_id(
    http_client,
    manager_user,
    admin_user,
    auth_headers_for,
    acme_client,
    gst_service_type,
):
    headers = auth_headers_for(manager_user)
    engagement = await _create_engagement(
        http_client, headers, acme_client, gst_service_type, manager_user
    )
    other_client = await http_client.post(
        "/api/v1/clients",
        headers=auth_headers_for(admin_user),
        json={"name": "Other Client Ltd"},
    )
    assert other_client.status_code == 201

    response = await http_client.patch(
        f"/api/v1/engagements/{engagement['id']}",
        headers=headers,
        json={"client_id": str(other_client.json()["id"])},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_patch_service_type(http_client, admin_user, auth_headers_for):
    headers = auth_headers_for(admin_user)
    created = await http_client.post(
        "/api/v1/service-types", headers=headers, json={"name": "Payroll"}
    )
    service_type_id = created.json()["id"]

    response = await http_client.patch(
        f"/api/v1/service-types/{service_type_id}",
        headers=headers,
        json={"description": "Monthly payroll processing", "is_active": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Monthly payroll processing"
    assert body["is_active"] is False


@pytest.mark.asyncio
async def test_patch_service_type_duplicate_name_is_rejected(
    http_client, admin_user, auth_headers_for
):
    headers = auth_headers_for(admin_user)
    await http_client.post("/api/v1/service-types", headers=headers, json={"name": "Payroll"})
    other = await http_client.post(
        "/api/v1/service-types", headers=headers, json={"name": "Audit"}
    )

    response = await http_client.patch(
        f"/api/v1/service-types/{other.json()['id']}",
        headers=headers,
        json={"name": "Payroll"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_delete_task_template_nulls_reference_and_keeps_task_intact(
    http_client, assigned_task, admin_user, gst_service_type, auth_headers_for
):
    headers = auth_headers_for(admin_user)
    template_id = str(assigned_task.task_template_id)
    original_title = assigned_task.title
    original_due_date = assigned_task.due_date.isoformat()

    response = await http_client.delete(
        f"/api/v1/task-templates/{template_id}", headers=headers
    )
    assert response.status_code == 204

    task_response = await http_client.get(
        f"/api/v1/tasks/{assigned_task.id}", headers=headers
    )
    assert task_response.status_code == 200
    body = task_response.json()
    assert body["task_template_id"] is None
    assert body["title"] == original_title
    assert body["due_date"] == original_due_date
