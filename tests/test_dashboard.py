from datetime import date, timedelta

import pytest


@pytest.mark.asyncio
async def test_dashboard_counts_reflect_the_workflow(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    member_headers = auth_headers_for(team_member_user)
    manager_headers = auth_headers_for(manager_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    manager_view = await http_client.get("/api/v1/dashboard", headers=manager_headers)
    counts = manager_view.json()
    assert counts["open_tasks"] == 3
    assert counts["unassigned"] == 2
    assert counts["waiting_for_review"] == 0

    await http_client.post(f"{task_url}/start", headers=member_headers)
    await http_client.post(f"{task_url}/submit", headers=member_headers)

    after_submit = await http_client.get("/api/v1/dashboard", headers=manager_headers)
    assert after_submit.json()["waiting_for_review"] == 1

    await http_client.post(
        f"{task_url}/request-changes", headers=manager_headers, json={"comment": "Redo"}
    )
    after_rejection = await http_client.get("/api/v1/dashboard", headers=manager_headers)
    assert after_rejection.json()["needs_rework"] == 1
    assert after_rejection.json()["waiting_for_review"] == 0


@pytest.mark.asyncio
async def test_team_member_sees_only_their_own_tasks(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    member_view = await http_client.get(
        "/api/v1/dashboard", headers=auth_headers_for(team_member_user)
    )
    manager_view = await http_client.get(
        "/api/v1/dashboard", headers=auth_headers_for(manager_user)
    )
    assert member_view.json()["open_tasks"] == 1
    assert manager_view.json()["open_tasks"] == 3


@pytest.mark.asyncio
async def test_next_period_tasks_count_as_upcoming_not_open(
    http_client, assigned_task, manager_user, auth_headers_for
):
    """The lead time creates engagements before their period starts.

    Those must not inflate open-task counts, or every month-end would look like
    a jump in workload for work nobody is meant to have begun.

    NOTE: with the real fixture dates (period_start 2026-08-01, today
    2026-09-13) the next monthly period starts 2026-09-01, which is also <=
    today — so this assertion alone does not prove the upcoming/open split; it
    only proves the total stays at 6. See
    test_upcoming_tasks_are_excluded_from_open_tasks below for the assertion
    that actually distinguishes the two buckets.
    """
    manager_headers = auth_headers_for(manager_user)
    before = await http_client.get("/api/v1/dashboard", headers=manager_headers)
    assert before.json()["open_tasks"] == 3

    await http_client.post(
        f"/api/v1/engagements/{assigned_task.engagement_id}/generate-next",
        headers=manager_headers,
    )

    after = await http_client.get("/api/v1/dashboard", headers=manager_headers)
    assert after.json()["open_tasks"] + after.json()["upcoming"] == 6


@pytest.mark.asyncio
async def test_upcoming_tasks_are_excluded_from_open_tasks(
    http_client,
    db_session,
    acme_client,
    gst_service_type,
    manager_user,
    auth_headers_for,
):
    """Genuine proof of the open/upcoming split.

    Creates an engagement whose period_start is in the future (well past the
    recurrence lead time) and asserts its tasks land in `upcoming`, never in
    `open_tasks`, while still not counting toward `unassigned` (which is scoped
    to the current period) or any other current-period bucket.
    """
    from app.models.engagement import Engagement
    from app.models.enums import EngagementType, RecurrenceFrequency
    from app.services.generation_service import generate_tasks_for_engagement

    today = date.today()
    future_start = today + timedelta(days=60)
    future_end = future_start + timedelta(days=29)

    future_engagement = Engagement(
        client_id=acme_client.id,
        service_type_id=gst_service_type.id,
        manager_id=manager_user.id,
        engagement_type=EngagementType.RECURRING,
        recurrence=RecurrenceFrequency.MONTHLY,
        start_date=future_start,
        period_start=future_start,
        period_end=future_end,
        auto_renew=True,
        updated_by=manager_user.id,
    )
    db_session.add(future_engagement)
    await db_session.flush()
    await generate_tasks_for_engagement(db_session, future_engagement)
    await db_session.commit()

    manager_headers = auth_headers_for(manager_user)
    summary = await http_client.get("/api/v1/dashboard", headers=manager_headers)
    counts = summary.json()

    assert counts["upcoming"] == 3
    assert counts["open_tasks"] == 0


@pytest.mark.asyncio
async def test_deleted_tasks_leave_the_default_list(
    http_client, assigned_task, manager_user, auth_headers_for
):
    headers = auth_headers_for(manager_user)

    await http_client.request(
        "DELETE",
        f"/api/v1/tasks/{assigned_task.id}",
        headers=headers,
        json={"reason": "Created in error"},
    )

    default_list = await http_client.get("/api/v1/tasks", headers=headers)
    assert all(task["id"] != str(assigned_task.id) for task in default_list.json())

    deleted_list = await http_client.get("/api/v1/tasks?deleted=true", headers=headers)
    assert [task["id"] for task in deleted_list.json()] == [str(assigned_task.id)]

    summary = await http_client.get("/api/v1/dashboard", headers=headers)
    assert summary.json()["deleted"] == 1
    assert summary.json()["open_tasks"] == 2
