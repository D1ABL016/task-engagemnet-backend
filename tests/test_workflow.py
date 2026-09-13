import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_happy_path_start_submit_approve(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    member_headers = auth_headers_for(team_member_user)
    manager_headers = auth_headers_for(manager_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    started = await http_client.post(f"{task_url}/start", headers=member_headers)
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"

    submitted = await http_client.post(f"{task_url}/submit", headers=member_headers)
    assert submitted.json()["status"] == "ready_for_review"

    approved = await http_client.post(
        f"{task_url}/approve", headers=manager_headers, json={"comment": "Looks right"}
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "completed"
    assert len(body["reviews"]) == 1
    assert body["reviews"][0]["decision"] == "approved"


@pytest.mark.asyncio
async def test_invalid_transition_is_rejected(
    http_client, assigned_task, team_member_user, auth_headers_for
):
    """assigned -> ready_for_review skips the work entirely."""
    response = await http_client.post(
        f"/api/v1/tasks/{assigned_task.id}/submit",
        headers=auth_headers_for(team_member_user),
    )
    assert response.status_code == 409
    assert "assigned" in response.json()["detail"]

    unchanged = await http_client.get(
        f"/api/v1/tasks/{assigned_task.id}", headers=auth_headers_for(team_member_user)
    )
    assert unchanged.json()["status"] == "assigned"


@pytest.mark.asyncio
async def test_another_team_member_cannot_update_this_task(
    http_client, assigned_task, other_team_member_user, auth_headers_for
):
    response = await http_client.post(
        f"/api/v1/tasks/{assigned_task.id}/start",
        headers=auth_headers_for(other_team_member_user),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_check_constraint_rejects_assignee_equal_reviewer(
    db_session, assigned_task, manager_user
):
    """The database-level guarantee: assignee_id == reviewer_id can never be stored.

    This is the layer that can never be talked out of the rule, whatever code
    writes the row. It is deliberately separate from the runtime-guard test
    below, which exercises the /approve endpoint instead.
    """
    from sqlalchemy.exc import IntegrityError

    assigned_task.assignee_id = manager_user.id
    assigned_task.reviewer_id = manager_user.id
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_user_cannot_approve_their_own_work(
    http_client,
    db_session,
    assigned_task,
    admin_user,
    manager_user,
    auth_headers_for,
):
    """The runtime guard: nobody approves their own work, even an admin.

    The task_reviewer_is_not_assignee CHECK constraint means a task's *named*
    reviewer can never equal its assignee, so a plain manager who is the
    assignee but not the reviewer is already refused by the relational
    authorization check ("only this task's reviewer or an admin may review
    it") before the self-approval guard is ever reached -- that path is
    covered by test_only_the_named_reviewer_may_approve.

    The one way the self-approval guard is genuinely reachable through the
    endpoint is the admin bypass: an Admin is not required to be the named
    reviewer to act on a review action, so this constructs the scenario the
    way it would really arise -- an Admin is the *assignee* of a task
    reviewed by someone else (manager_user), and that Admin then tries to
    approve their own submitted work using their admin privilege. The
    relational check waves them through (they're an admin); the self-approval
    guard must still refuse them.
    """
    admin_headers = auth_headers_for(admin_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    assigned_task.assignee_id = admin_user.id
    assigned_task.reviewer_id = manager_user.id
    await db_session.commit()

    started = await http_client.post(f"{task_url}/start", headers=admin_headers)
    assert started.status_code == 200

    submitted = await http_client.post(f"{task_url}/submit", headers=admin_headers)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "ready_for_review"

    response = await http_client.post(
        f"{task_url}/approve",
        headers=admin_headers,
        json={"comment": "Approving my own work"},
    )
    assert response.status_code == 409

    from app.models.task import TaskReview

    result = await db_session.execute(
        select(TaskReview).where(TaskReview.task_id == assigned_task.id)
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_request_changes_requires_a_comment(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    member_headers = auth_headers_for(team_member_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    await http_client.post(f"{task_url}/start", headers=member_headers)
    await http_client.post(f"{task_url}/submit", headers=member_headers)

    response = await http_client.post(
        f"{task_url}/request-changes",
        headers=auth_headers_for(manager_user),
        json={"comment": ""},
    )
    assert response.status_code == 422

    still_pending = await http_client.get(task_url, headers=member_headers)
    assert still_pending.json()["status"] == "ready_for_review"
    assert still_pending.json()["reviews"] == []


@pytest.mark.asyncio
async def test_changes_requested_round_trip(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    member_headers = auth_headers_for(team_member_user)
    manager_headers = auth_headers_for(manager_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    await http_client.post(f"{task_url}/start", headers=member_headers)
    await http_client.post(f"{task_url}/submit", headers=member_headers)

    sent_back = await http_client.post(
        f"{task_url}/request-changes",
        headers=manager_headers,
        json={"comment": "Invoice 4412 is missing"},
    )
    assert sent_back.json()["status"] == "changes_requested"

    resumed = await http_client.post(f"{task_url}/resume", headers=member_headers)
    assert resumed.json()["status"] == "in_progress"
    assert resumed.json()["reviews"][0]["comment"] == "Invoice 4412 is missing"


@pytest.mark.asyncio
async def test_only_the_named_reviewer_may_approve(
    http_client, assigned_task, team_member_user, other_manager_user, auth_headers_for
):
    member_headers = auth_headers_for(team_member_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    await http_client.post(f"{task_url}/start", headers=member_headers)
    await http_client.post(f"{task_url}/submit", headers=member_headers)

    response = await http_client.post(
        f"{task_url}/approve", headers=auth_headers_for(other_manager_user), json={}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_manager_can_reopen_a_completed_task(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    member_headers = auth_headers_for(team_member_user)
    manager_headers = auth_headers_for(manager_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    await http_client.post(f"{task_url}/start", headers=member_headers)
    await http_client.post(f"{task_url}/submit", headers=member_headers)
    await http_client.post(f"{task_url}/approve", headers=manager_headers, json={})

    reopened = await http_client.post(
        f"{task_url}/reopen",
        headers=manager_headers,
        json={"comment": "Filed against the wrong quarter"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "in_progress"
    assert [review["decision"] for review in reopened.json()["reviews"]] == [
        "approved",
        "reopened",
    ]
