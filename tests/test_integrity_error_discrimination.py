"""An IntegrityError that is NOT the specific constraint a service checks for
must never be mislabelled as that constraint's error, and must not be
swallowed. These exercise the service functions directly (with a stub
session) so the DB-level constraint that would trigger some other violation
never has to actually fire.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import UserRole
from app.schemas.service_type import ServiceTypeCreate, TaskTemplateCreate
from app.schemas.user import UserCreate
from app.services import service_type_service, user_service


def _stub_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _integrity_error(constraint_text: str) -> IntegrityError:
    return IntegrityError("STATEMENT", {}, Exception(constraint_text))


@pytest.mark.asyncio
async def test_create_user_does_not_mislabel_unrelated_integrity_error():
    session = _stub_session()
    session.commit.side_effect = _integrity_error("some_unrelated_fk_violation")
    payload = UserCreate(
        email="someone@example.com",
        full_name="Someone",
        password="a-long-enough-password",
        role=UserRole.TEAM_MEMBER,
    )

    with pytest.raises(IntegrityError):
        await user_service.create_user(session, payload)

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_service_type_does_not_mislabel_unrelated_integrity_error():
    session = _stub_session()
    session.commit.side_effect = _integrity_error("some_unrelated_fk_violation")
    payload = ServiceTypeCreate(name="Anything")

    with pytest.raises(IntegrityError):
        await service_type_service.create_service_type(session, payload, uuid.uuid4())

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_task_template_does_not_mislabel_unrelated_integrity_error(monkeypatch):
    session = _stub_session()
    session.commit.side_effect = _integrity_error("some_unrelated_fk_violation")

    async def _fake_load_service_type(_session, _service_type_id):
        return MagicMock()

    monkeypatch.setattr(
        service_type_service, "load_service_type", _fake_load_service_type
    )
    payload = TaskTemplateCreate(title="Do the thing", sequence=1, default_offset_days=0)

    with pytest.raises(IntegrityError):
        await service_type_service.add_task_template(
            session, uuid.uuid4(), payload, uuid.uuid4()
        )

    session.rollback.assert_awaited_once()
