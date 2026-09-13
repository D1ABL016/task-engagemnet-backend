from app.models.enums import TaskStatus, UserRole


def test_task_status_has_seven_states():
    assert len(TaskStatus) == 7
    assert TaskStatus.ASSIGNED.value == "assigned"


def test_user_roles_match_the_spec():
    assert {role.value for role in UserRole} == {"admin", "manager", "team_member"}
