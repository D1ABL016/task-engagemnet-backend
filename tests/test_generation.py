import pytest


def _engagement_payload(acme_client, gst_service_type, manager_user, **overrides):
    payload = {
        "client_id": str(acme_client.id),
        "service_type_id": str(gst_service_type.id),
        "manager_id": str(manager_user.id),
        "engagement_type": "recurring",
        "recurrence": "monthly",
        "start_date": "2026-08-17",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_creating_an_engagement_generates_tasks_from_templates(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    response = await http_client.post(
        "/api/v1/engagements",
        headers=auth_headers_for(manager_user),
        json=_engagement_payload(acme_client, gst_service_type, manager_user),
    )
    assert response.status_code == 201
    body = response.json()

    assert body["period_start"] == "2026-08-01"
    assert body["period_end"] == "2026-08-31"
    assert body["start_date"] == "2026-08-01"

    tasks = sorted(body["tasks"], key=lambda task: task["sequence"])
    assert [task["title"] for task in tasks] == [
        "Collect invoices",
        "Reconcile register",
        "File return",
    ]
    assert [task["due_date"] for task in tasks] == ["2026-08-01", "2026-08-06", "2026-08-13"]
    assert all(task["status"] == "not_started" for task in tasks)
    assert all(task["assignee_id"] is None for task in tasks)
    assert all(task["reviewer_id"] == str(manager_user.id) for task in tasks)


@pytest.mark.asyncio
async def test_one_time_engagement_resolves_due_dates_from_start_date(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    response = await http_client.post(
        "/api/v1/engagements",
        headers=auth_headers_for(manager_user),
        json=_engagement_payload(
            acme_client,
            gst_service_type,
            manager_user,
            engagement_type="one_time",
            recurrence=None,
            start_date="2026-09-14",
        ),
    )
    assert response.status_code == 201
    body = response.json()

    assert body["period_start"] is None
    assert body["start_date"] == "2026-09-14"
    tasks = sorted(body["tasks"], key=lambda task: task["sequence"])
    assert [task["due_date"] for task in tasks] == ["2026-09-14", "2026-09-19", "2026-09-26"]


@pytest.mark.asyncio
async def test_duplicate_recurring_engagement_is_rejected(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    payload = _engagement_payload(acme_client, gst_service_type, manager_user)

    first = await http_client.post("/api/v1/engagements", headers=headers, json=payload)
    assert first.status_code == 201

    # A different day inside the same month is still the same period.
    payload["start_date"] = "2026-08-28"
    second = await http_client.post("/api/v1/engagements", headers=headers, json=payload)
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


@pytest.mark.asyncio
async def test_two_one_time_engagements_are_both_allowed(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    """Two GST Refunds for one client are two legitimate refund claims."""
    headers = auth_headers_for(manager_user)
    payload = _engagement_payload(
        acme_client,
        gst_service_type,
        manager_user,
        engagement_type="one_time",
        recurrence=None,
        start_date="2026-09-14",
    )

    first = await http_client.post("/api/v1/engagements", headers=headers, json=payload)
    second = await http_client.post("/api/v1/engagements", headers=headers, json=payload)
    assert first.status_code == 201
    assert second.status_code == 201


@pytest.mark.asyncio
async def test_recurring_engagement_without_recurrence_is_rejected(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    response = await http_client.post(
        "/api/v1/engagements",
        headers=auth_headers_for(manager_user),
        json=_engagement_payload(
            acme_client, gst_service_type, manager_user, recurrence=None
        ),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_team_member_cannot_create_an_engagement(
    http_client, team_member_user, auth_headers_for, acme_client, gst_service_type, manager_user
):
    response = await http_client.post(
        "/api/v1/engagements",
        headers=auth_headers_for(team_member_user),
        json=_engagement_payload(acme_client, gst_service_type, manager_user),
    )
    assert response.status_code == 403
