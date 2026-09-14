"""Tests for the final-review fixes: task/engagement read visibility (Fix 1,
Fix 2, Fix 4), the assignment PATCH's absent-vs-null distinction (Fix 3), the
review-route role guard (Fix 5), and reference validation on assignment (Fix 6).
"""
import uuid

import pytest


# ---------------------------------------------------------------------------
# Fix 1: GET /tasks/{id} ownership filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_member_cannot_read_a_task_they_are_not_party_to(
    http_client, assigned_task, other_team_member_user, auth_headers_for
):
    """assigned_task's assignee/reviewer are team_member_user/manager_user; a
    third team member with no relationship to it must get 404, not 403 or 200.
    """
    response = await http_client.get(
        f"/api/v1/tasks/{assigned_task.id}",
        headers=auth_headers_for(other_team_member_user),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_named_reviewer_can_read_a_task_even_if_not_the_assignee(
    http_client, db_session, assigned_task, manager_user, auth_headers_for
):
    """Reviewer-based visibility applies to a manager, not a team member.

    A team member always sees only tasks assigned to them — being named
    reviewer on a task grants visibility only for the manager role.
    """
    assigned_task.reviewer_id = manager_user.id
    await db_session.commit()

    response = await http_client.get(
        f"/api/v1/tasks/{assigned_task.id}",
        headers=auth_headers_for(manager_user),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reviewer_id_grants_no_visibility_to_a_team_member(
    http_client, db_session, assigned_task, other_team_member_user, auth_headers_for
):
    assigned_task.reviewer_id = other_team_member_user.id
    await db_session.commit()

    response = await http_client.get(
        f"/api/v1/tasks/{assigned_task.id}",
        headers=auth_headers_for(other_team_member_user),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_assignee_can_read_their_own_task(
    http_client, assigned_task, team_member_user, auth_headers_for
):
    response = await http_client.get(
        f"/api/v1/tasks/{assigned_task.id}", headers=auth_headers_for(team_member_user)
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_manager_can_read_any_task(
    http_client, assigned_task, manager_user, auth_headers_for
):
    response = await http_client.get(
        f"/api/v1/tasks/{assigned_task.id}", headers=auth_headers_for(manager_user)
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Fix 2: GET /engagements and GET /engagements/{id} role/relational filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_member_engagement_list_only_includes_engagements_with_their_own_tasks(
    http_client,
    assigned_task,
    manager_user,
    team_member_user,
    other_team_member_user,
    acme_client,
    gst_service_type,
    auth_headers_for,
):
    manager_headers = auth_headers_for(manager_user)
    # A second, unrelated one-time engagement neither team member has a task in.
    await http_client.post(
        "/api/v1/engagements",
        headers=manager_headers,
        json={
            "client_id": str(acme_client.id),
            "service_type_id": str(gst_service_type.id),
            "manager_id": str(manager_user.id),
            "engagement_type": "one_time",
            "start_date": "2026-09-14",
        },
    )

    own_listing = await http_client.get(
        "/api/v1/engagements", headers=auth_headers_for(team_member_user)
    )
    assert own_listing.status_code == 200
    engagement_ids = {row["id"] for row in own_listing.json()}
    assert str(assigned_task.engagement_id) in engagement_ids
    assert len(own_listing.json()) == 1

    unrelated_listing = await http_client.get(
        "/api/v1/engagements", headers=auth_headers_for(other_team_member_user)
    )
    assert unrelated_listing.status_code == 200
    assert unrelated_listing.json() == []


@pytest.mark.asyncio
async def test_team_member_engagement_detail_404_when_no_task_in_it(
    http_client,
    manager_user,
    other_team_member_user,
    acme_client,
    gst_service_type,
    auth_headers_for,
):
    created = await http_client.post(
        "/api/v1/engagements",
        headers=auth_headers_for(manager_user),
        json={
            "client_id": str(acme_client.id),
            "service_type_id": str(gst_service_type.id),
            "manager_id": str(manager_user.id),
            "engagement_type": "one_time",
            "start_date": "2026-09-15",
        },
    )
    engagement_id = created.json()["id"]

    response = await http_client.get(
        f"/api/v1/engagements/{engagement_id}",
        headers=auth_headers_for(other_team_member_user),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_team_member_engagement_detail_embeds_only_their_own_tasks(
    http_client, assigned_task, team_member_user, auth_headers_for
):
    """The engagement has three tasks; team_member_user is the assignee of only
    the first. Reading the engagement must not leak the other two.
    """
    response = await http_client.get(
        f"/api/v1/engagements/{assigned_task.engagement_id}",
        headers=auth_headers_for(team_member_user),
    )
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert [task["id"] for task in tasks] == [str(assigned_task.id)]


@pytest.mark.asyncio
async def test_manager_sees_all_tasks_embedded_in_an_engagement(
    http_client, assigned_task, manager_user, auth_headers_for
):
    response = await http_client.get(
        f"/api/v1/engagements/{assigned_task.engagement_id}",
        headers=auth_headers_for(manager_user),
    )
    assert response.status_code == 200
    assert len(response.json()["tasks"]) == 3


# ---------------------------------------------------------------------------
# Fix 4: soft-deleted tasks excluded from Engagement.tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleted_task_is_absent_from_its_engagement(
    http_client, assigned_task, manager_user, auth_headers_for
):
    manager_headers = auth_headers_for(manager_user)
    deleted = await http_client.request(
        "DELETE",
        f"/api/v1/tasks/{assigned_task.id}",
        headers=manager_headers,
        json={"reason": "Duplicate"},
    )
    assert deleted.status_code == 200

    engagement = await http_client.get(
        f"/api/v1/engagements/{assigned_task.engagement_id}", headers=manager_headers
    )
    assert engagement.status_code == 200
    task_ids = {task["id"] for task in engagement.json()["tasks"]}
    assert str(assigned_task.id) not in task_ids


# ---------------------------------------------------------------------------
# Fix 3: absent vs. explicit null on PATCH /tasks/{id}/assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_changing_only_the_reviewer_on_an_in_progress_task_leaves_assignee_and_status(
    http_client,
    assigned_task,
    team_member_user,
    other_team_member_user,
    admin_user,
    auth_headers_for,
):
    """Only an admin may change a task's reviewer."""
    task_url = f"/api/v1/tasks/{assigned_task.id}"
    await http_client.post(f"{task_url}/start", headers=auth_headers_for(team_member_user))

    response = await http_client.patch(
        f"{task_url}/assignment",
        headers=auth_headers_for(admin_user),
        json={"reviewer_id": str(other_team_member_user.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["assignee_id"] == str(team_member_user.id)
    assert body["reviewer_id"] == str(other_team_member_user.id)


@pytest.mark.asyncio
async def test_manager_cannot_change_a_task_reviewer(
    http_client, assigned_task, manager_user, other_team_member_user, auth_headers_for
):
    response = await http_client.patch(
        f"/api/v1/tasks/{assigned_task.id}/assignment",
        headers=auth_headers_for(manager_user),
        json={"reviewer_id": str(other_team_member_user.id)},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_explicit_null_assignee_still_unassigns_an_assigned_task(
    http_client, assigned_task, manager_user, auth_headers_for
):
    response = await http_client.patch(
        f"/api/v1/tasks/{assigned_task.id}/assignment",
        headers=auth_headers_for(manager_user),
        json={"assignee_id": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_started"
    assert body["assignee_id"] is None


@pytest.mark.asyncio
async def test_omitting_reviewer_leaves_it_unchanged_when_only_assignee_is_sent(
    http_client,
    assigned_task,
    other_team_member_user,
    manager_user,
    auth_headers_for,
):
    original_reviewer_id = str(assigned_task.reviewer_id)
    response = await http_client.patch(
        f"/api/v1/tasks/{assigned_task.id}/assignment",
        headers=auth_headers_for(manager_user),
        json={"assignee_id": str(other_team_member_user.id)},
    )
    assert response.status_code == 200
    assert response.json()["reviewer_id"] == original_reviewer_id


# ---------------------------------------------------------------------------
# Fix 5: review actions gated by the relational check, not require_manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_team_member_named_as_reviewer_can_approve(
    http_client,
    db_session,
    assigned_task,
    team_member_user,
    other_team_member_user,
    auth_headers_for,
):
    assigned_task.reviewer_id = other_team_member_user.id
    await db_session.commit()

    member_headers = auth_headers_for(team_member_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"
    await http_client.post(f"{task_url}/start", headers=member_headers)
    await http_client.post(f"{task_url}/submit", headers=member_headers)

    response = await http_client.post(
        f"{task_url}/approve",
        headers=auth_headers_for(other_team_member_user),
        json={"comment": "Looks fine"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# Fix 6: assignee_id/reviewer_id are validated, never a bare 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assigning_a_nonexistent_user_is_rejected_cleanly(
    http_client, assigned_task, manager_user, auth_headers_for
):
    bogus_user_id = uuid.uuid4()
    response = await http_client.patch(
        f"/api/v1/tasks/{assigned_task.id}/assignment",
        headers=auth_headers_for(manager_user),
        json={"assignee_id": str(bogus_user_id)},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_naming_a_nonexistent_reviewer_is_rejected_cleanly(
    http_client, assigned_task, admin_user, auth_headers_for
):
    bogus_user_id = uuid.uuid4()
    response = await http_client.patch(
        f"/api/v1/tasks/{assigned_task.id}/assignment",
        headers=auth_headers_for(admin_user),
        json={"reviewer_id": str(bogus_user_id)},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_adhoc_task_with_a_nonexistent_assignee_is_rejected_cleanly(
    http_client, assigned_task, manager_user, auth_headers_for
):
    bogus_user_id = uuid.uuid4()
    response = await http_client.post(
        f"/api/v1/engagements/{assigned_task.engagement_id}/tasks",
        headers=auth_headers_for(manager_user),
        json={"title": "Chase client", "assignee_id": str(bogus_user_id)},
    )
    assert response.status_code == 409
