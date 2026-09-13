import os
import uuid

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")

from app.config import Settings

settings = Settings()
if not settings.test_database_url:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. Tests refuse to run against the "
        "development database. Set it in backend/.env."
    )
os.environ["DATABASE_URL"] = settings.test_database_url

TEST_PASSWORD = "test-password"


@pytest_asyncio.fixture
async def http_client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session():
    from app.database import async_session_factory

    async with async_session_factory() as session:
        yield session


async def _create_user(db_session, email, full_name, role):
    from app.core.security import hash_password
    from app.models.user import AppUser

    user = AppUser(
        id=uuid.uuid4(),
        email=email,
        full_name=full_name,
        hashed_password=hash_password(TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session):
    from app.models.enums import UserRole

    return await _create_user(
        db_session, f"admin-{uuid.uuid4()}@example.com", "Test Admin", UserRole.ADMIN
    )


@pytest_asyncio.fixture
async def manager_user(db_session):
    from app.models.enums import UserRole

    return await _create_user(
        db_session,
        f"manager-{uuid.uuid4()}@example.com",
        "Test Manager",
        UserRole.MANAGER,
    )


@pytest_asyncio.fixture
async def other_manager_user(db_session):
    from app.models.enums import UserRole

    return await _create_user(
        db_session,
        f"manager2-{uuid.uuid4()}@example.com",
        "Test Other Manager",
        UserRole.MANAGER,
    )


@pytest_asyncio.fixture
async def team_member_user(db_session):
    from app.models.enums import UserRole

    return await _create_user(
        db_session,
        f"team-member-{uuid.uuid4()}@example.com",
        "Test Team Member",
        UserRole.TEAM_MEMBER,
    )


@pytest_asyncio.fixture
async def other_team_member_user(db_session):
    from app.models.enums import UserRole

    return await _create_user(
        db_session,
        f"team-member2-{uuid.uuid4()}@example.com",
        "Test Other Team Member",
        UserRole.TEAM_MEMBER,
    )


@pytest.fixture
def auth_headers_for():
    from app.core.security import create_access_token

    def make_headers(user) -> dict[str, str]:
        token = create_access_token(user.id, user.role)
        return {"Authorization": f"Bearer {token}"}

    return make_headers


@pytest_asyncio.fixture
async def gst_service_type(db_session, admin_user):
    """A service type with three templates, offsets 0, 5 and 12 days."""
    from app.models.service_type import ServiceType, TaskTemplate

    service_type = ServiceType(
        name="Monthly GST Compliance", is_active=True, updated_by=admin_user.id
    )
    db_session.add(service_type)
    await db_session.flush()

    for sequence, (title, offset) in enumerate(
        [("Collect invoices", 0), ("Reconcile register", 5), ("File return", 12)], start=1
    ):
        db_session.add(
            TaskTemplate(
                service_type_id=service_type.id,
                title=title,
                sequence=sequence,
                default_offset_days=offset,
                updated_by=admin_user.id,
            )
        )
    await db_session.commit()
    await db_session.refresh(service_type)
    return service_type


@pytest_asyncio.fixture
async def acme_client(db_session, admin_user):
    from app.models.client import Client

    client = Client(name="Acme Ltd", is_active=True, updated_by=admin_user.id)
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(client)
    return client


@pytest_asyncio.fixture
async def assigned_task(
    db_session, acme_client, gst_service_type, manager_user, team_member_user
):
    """One engagement with three tasks; the first is assigned and ready to start."""
    from datetime import date

    from app.models.engagement import Engagement
    from app.models.enums import EngagementType, RecurrenceFrequency, TaskStatus
    from app.services.generation_service import generate_tasks_for_engagement

    engagement = Engagement(
        client_id=acme_client.id,
        service_type_id=gst_service_type.id,
        manager_id=manager_user.id,
        engagement_type=EngagementType.RECURRING,
        recurrence=RecurrenceFrequency.MONTHLY,
        start_date=date(2026, 8, 1),
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        auto_renew=True,
        updated_by=manager_user.id,
    )
    db_session.add(engagement)
    await db_session.flush()

    tasks = await generate_tasks_for_engagement(db_session, engagement)
    first_task = tasks[0]
    first_task.assignee_id = team_member_user.id
    first_task.status = TaskStatus.ASSIGNED
    await db_session.commit()
    await db_session.refresh(first_task)
    return first_task


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables():
    from sqlalchemy import text

    from app.database import async_session_factory, engine

    yield
    async with async_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE task_review, task, engagement, task_template, "
                "service_type, client, app_user RESTART IDENTITY CASCADE"
            )
        )
        await session.execute(
            text(
                "TRUNCATE client_audit, service_type_audit, task_template_audit, "
                "engagement_audit, task_audit RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    # Each test runs in its own event loop (pytest-asyncio, function-scoped),
    # but the engine's connection pool is a module-level singleton. Dispose it
    # after every test so no pooled asyncpg connection tied to this test's now-
    # closing loop is handed to a later test running on a different loop.
    await engine.dispose()
