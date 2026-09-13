import uuid
from datetime import date

import pytest

from app.database import async_session_factory
from app.services.generation_service import (
    find_series_due_for_generation,
    run_recurrence_generation,
)


@pytest.mark.asyncio
async def test_generate_next_creates_the_following_period(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    created = await http_client.post(
        "/api/v1/engagements",
        headers=headers,
        json={
            "client_id": str(acme_client.id),
            "service_type_id": str(gst_service_type.id),
            "manager_id": str(manager_user.id),
            "engagement_type": "recurring",
            "recurrence": "monthly",
            "start_date": "2026-08-01",
        },
    )
    engagement_id = created.json()["id"]

    response = await http_client.post(
        f"/api/v1/engagements/{engagement_id}/generate-next", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["engagement"]["period_start"] == "2026-09-01"
    assert body["engagement"]["period_end"] == "2026-09-30"
    assert len(body["engagement"]["tasks"]) == 3
    assert body["engagement"]["tasks"][0]["due_date"] == "2026-09-01"


@pytest.mark.asyncio
async def test_generating_twice_creates_it_once(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    created = await http_client.post(
        "/api/v1/engagements",
        headers=headers,
        json={
            "client_id": str(acme_client.id),
            "service_type_id": str(gst_service_type.id),
            "manager_id": str(manager_user.id),
            "engagement_type": "recurring",
            "recurrence": "monthly",
            "start_date": "2026-08-01",
        },
    )
    engagement_id = created.json()["id"]

    first = await http_client.post(
        f"/api/v1/engagements/{engagement_id}/generate-next", headers=headers
    )
    second = await http_client.post(
        f"/api/v1/engagements/{engagement_id}/generate-next", headers=headers
    )

    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["engagement"]["id"] == second.json()["engagement"]["id"]

    listing = await http_client.get("/api/v1/engagements", headers=headers)
    september = [
        engagement
        for engagement in listing.json()
        if engagement["period_start"] == "2026-09-01"
    ]
    assert len(september) == 1


@pytest.mark.asyncio
async def test_series_with_auto_renew_off_is_not_due(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type, db_session
):
    headers = auth_headers_for(manager_user)
    created = await http_client.post(
        "/api/v1/engagements",
        headers=headers,
        json={
            "client_id": str(acme_client.id),
            "service_type_id": str(gst_service_type.id),
            "manager_id": str(manager_user.id),
            "engagement_type": "recurring",
            "recurrence": "monthly",
            "start_date": "2026-08-01",
        },
    )
    engagement_id = created.json()["id"]

    await http_client.patch(
        f"/api/v1/engagements/{engagement_id}/auto-renew",
        headers=headers,
        json={"enabled": False},
    )

    due = await find_series_due_for_generation(db_session, as_of=date(2026, 8, 30))
    assert due == []


@pytest.mark.asyncio
async def test_scheduled_run_is_idempotent(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type
):
    headers = auth_headers_for(manager_user)
    await http_client.post(
        "/api/v1/engagements",
        headers=headers,
        json={
            "client_id": str(acme_client.id),
            "service_type_id": str(gst_service_type.id),
            "manager_id": str(manager_user.id),
            "engagement_type": "recurring",
            "recurrence": "monthly",
            "start_date": "2026-08-01",
        },
    )

    first_run = await run_recurrence_generation(
        async_session_factory, as_of=date(2026, 8, 30)
    )
    second_run = await run_recurrence_generation(
        async_session_factory, as_of=date(2026, 8, 30)
    )

    assert first_run.created == 1
    assert first_run.failed == 0
    # The second run finds September as the latest period and October not yet
    # due, so there is nothing to do at all.
    assert second_run.created == 0
    assert second_run.failed == 0


@pytest.mark.asyncio
async def test_failed_generation_leaves_no_engagement(
    http_client, manager_user, auth_headers_for, acme_client, gst_service_type, db_session
):
    """If task generation fails, the engagement rolls back with it."""
    from sqlalchemy import delete, update

    from app.models.service_type import TaskTemplate
    from app.models.task import Task
    from app.services.generation_service import create_next_period
    from app.services.engagement_service import load_engagement

    headers = auth_headers_for(manager_user)
    created = await http_client.post(
        "/api/v1/engagements",
        headers=headers,
        json={
            "client_id": str(acme_client.id),
            "service_type_id": str(gst_service_type.id),
            "manager_id": str(manager_user.id),
            "engagement_type": "recurring",
            "recurrence": "monthly",
            "start_date": "2026-08-01",
        },
    )
    engagement_id = created.json()["id"]

    # The August engagement's own tasks reference these templates by FK, so
    # detach them first (nullable FK) before removing the templates so
    # generation raises after the engagement is flushed.
    await db_session.execute(
        update(Task)
        .where(Task.engagement_id == uuid.UUID(engagement_id))
        .values(task_template_id=None)
    )
    await db_session.execute(
        delete(TaskTemplate).where(TaskTemplate.service_type_id == gst_service_type.id)
    )
    await db_session.commit()

    engagement = await load_engagement(db_session, engagement_id)
    with pytest.raises(Exception):
        await create_next_period(db_session, engagement, actor_id=None)

    listing = await http_client.get("/api/v1/engagements", headers=headers)
    assert all(
        item["period_start"] != "2026-09-01" for item in listing.json()
    ), "the rolled-back engagement must not exist"
