import pytest


@pytest.mark.asyncio
async def test_assigning_a_not_started_task_moves_it_to_assigned(
    http_client, assigned_task, db_session, manager_user, other_team_member_user, auth_headers_for
):
    from app.models.enums import TaskStatus
    from app.models.task import Task
    from sqlalchemy import select

    result = await db_session.execute(
        select(Task).where(
            Task.engagement_id == assigned_task.engagement_id,
            Task.status == TaskStatus.NOT_STARTED,
        )
    )
    unassigned_task = result.scalars().first()

    response = await http_client.patch(
        f"/api/v1/tasks/{unassigned_task.id}/assignment",
        headers=auth_headers_for(manager_user),
        json={"assignee_id": str(other_team_member_user.id)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
    assert response.json()["assignee_id"] == str(other_team_member_user.id)


@pytest.mark.asyncio
async def test_reassigning_an_in_progress_task_keeps_its_status(
    http_client, assigned_task, team_member_user, other_team_member_user,
    manager_user, auth_headers_for
):
    task_url = f"/api/v1/tasks/{assigned_task.id}"
    await http_client.post(f"{task_url}/start", headers=auth_headers_for(team_member_user))

    response = await http_client.patch(
        f"{task_url}/assignment",
        headers=auth_headers_for(manager_user),
        json={"assignee_id": str(other_team_member_user.id)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["assignee_id"] == str(other_team_member_user.id)


@pytest.mark.asyncio
async def test_unassigning_an_in_progress_task_is_rejected(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    task_url = f"/api/v1/tasks/{assigned_task.id}"
    await http_client.post(f"{task_url}/start", headers=auth_headers_for(team_member_user))

    response = await http_client.patch(
        f"{task_url}/assignment",
        headers=auth_headers_for(manager_user),
        json={"assignee_id": None},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_team_member_cannot_assign_tasks(
    http_client, assigned_task, team_member_user, other_team_member_user, auth_headers_for
):
    response = await http_client.patch(
        f"/api/v1/tasks/{assigned_task.id}/assignment",
        headers=auth_headers_for(team_member_user),
        json={"assignee_id": str(other_team_member_user.id)},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_adhoc_task_sorts_last_and_has_no_template(
    http_client, assigned_task, manager_user, auth_headers_for
):
    response = await http_client.post(
        f"/api/v1/engagements/{assigned_task.engagement_id}/tasks",
        headers=auth_headers_for(manager_user),
        json={"title": "Chase client for missing PAN", "due_date": "2026-08-20"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["task_template_id"] is None
    assert body["sequence"] == 4
    assert body["status"] == "not_started"
    assert body["reviewer_id"] == str(manager_user.id)


@pytest.mark.asyncio
async def test_adhoc_task_is_not_carried_into_the_next_period(
    http_client, assigned_task, manager_user, auth_headers_for
):
    manager_headers = auth_headers_for(manager_user)
    await http_client.post(
        f"/api/v1/engagements/{assigned_task.engagement_id}/tasks",
        headers=manager_headers,
        json={"title": "One-off chase"},
    )

    generated = await http_client.post(
        f"/api/v1/engagements/{assigned_task.engagement_id}/generate-next",
        headers=manager_headers,
    )
    next_tasks = generated.json()["engagement"]["tasks"]
    assert len(next_tasks) == 3
    assert all(task["title"] != "One-off chase" for task in next_tasks)


@pytest.mark.asyncio
async def test_deleted_task_rejects_workflow_actions_and_restores_to_its_status(
    http_client, assigned_task, team_member_user, manager_user, auth_headers_for
):
    member_headers = auth_headers_for(team_member_user)
    manager_headers = auth_headers_for(manager_user)
    task_url = f"/api/v1/tasks/{assigned_task.id}"

    await http_client.post(f"{task_url}/start", headers=member_headers)

    deleted = await http_client.request(
        "DELETE", task_url, headers=manager_headers, json={"reason": "Duplicate of task 2"}
    )
    assert deleted.status_code == 200
    assert deleted.json()["deletion_reason"] == "Duplicate of task 2"
    assert deleted.json()["status"] == "in_progress", "status must be preserved"

    blocked = await http_client.post(f"{task_url}/submit", headers=member_headers)
    assert blocked.status_code == 409

    restored = await http_client.post(f"{task_url}/restore", headers=manager_headers)
    assert restored.status_code == 200
    assert restored.json()["status"] == "in_progress"
    assert restored.json()["deleted_at"] is None


@pytest.mark.asyncio
async def test_delete_requires_a_reason(
    http_client, assigned_task, manager_user, auth_headers_for
):
    response = await http_client.request(
        "DELETE",
        f"/api/v1/tasks/{assigned_task.id}",
        headers=auth_headers_for(manager_user),
        json={"reason": ""},
    )
    assert response.status_code == 422
