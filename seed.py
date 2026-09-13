"""Populate a database with demonstration data.

Idempotent by construction: it refuses to run against a database that already
has users, so re-running it cannot produce doubled clients or engagements.

All data here is invented. No real client or personal information.
"""

import asyncio
import logging
from datetime import date

from sqlalchemy import func, select

from app.core.periods import period_bounds
from app.core.security import hash_password
from app.database import async_session_factory
from app.models.client import Client
from app.models.engagement import Engagement
from app.models.enums import EngagementType, RecurrenceFrequency, TaskStatus, UserRole
from app.models.service_type import ServiceType, TaskTemplate
from app.models.user import AppUser
from app.services.generation_service import generate_tasks_for_engagement

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

DEMO_PASSWORD = "Demo1234!"

USERS = [
    ("admin@example.com", "Ada Admin", UserRole.ADMIN),
    ("priya.manager@example.com", "Priya Manager", UserRole.MANAGER),
    ("rahul.manager@example.com", "Rahul Manager", UserRole.MANAGER),
    ("sara.member@example.com", "Sara Member", UserRole.TEAM_MEMBER),
    ("omar.member@example.com", "Omar Member", UserRole.TEAM_MEMBER),
    ("lena.member@example.com", "Lena Member", UserRole.TEAM_MEMBER),
    ("kofi.member@example.com", "Kofi Member", UserRole.TEAM_MEMBER),
]

CLIENTS = [
    "Northwind Traders",
    "Blue Harbour Foods",
    "Kestrel Logistics",
    "Marigold Textiles",
    "Summit Analytics",
]

SERVICE_TYPES = [
    (
        "Monthly GST Compliance",
        "Monthly return preparation and filing.",
        [
            ("Collect invoices from client", 1, 0),
            ("Reconcile purchase register", 2, 5),
            ("Prepare GSTR-3B", 3, 10),
            ("File return", 4, 15),
        ],
    ),
    (
        "Quarterly TDS Filing",
        "Quarterly tax deducted at source return.",
        [
            ("Gather deduction statements", 1, 0),
            ("Validate PAN details", 2, 10),
            ("Prepare and file TDS return", 3, 25),
        ],
    ),
    (
        "GST Registration",
        "One-time registration for a new client.",
        [
            ("Collect incorporation documents", 1, 0),
            ("Submit registration application", 2, 3),
            ("Respond to queries and obtain GSTIN", 3, 10),
        ],
    ),
]


async def seed() -> None:
    async with async_session_factory() as session:
        existing_users = await session.scalar(select(func.count()).select_from(AppUser))
        if existing_users:
            logger.warning(
                "Database already contains %d users. Refusing to seed again.",
                existing_users,
            )
            return

        users = {}
        for email, full_name, role in USERS:
            user = AppUser(
                email=email,
                full_name=full_name,
                hashed_password=hash_password(DEMO_PASSWORD),
                role=role,
                is_active=True,
            )
            session.add(user)
            users[email] = user
        await session.flush()

        admin = users["admin@example.com"]
        managers = [users["priya.manager@example.com"], users["rahul.manager@example.com"]]
        members = [
            users["sara.member@example.com"],
            users["omar.member@example.com"],
            users["lena.member@example.com"],
            users["kofi.member@example.com"],
        ]

        clients = []
        for name in CLIENTS:
            client = Client(name=name, is_active=True, updated_by=admin.id)
            session.add(client)
            clients.append(client)

        service_types = []
        for name, description, templates in SERVICE_TYPES:
            service_type = ServiceType(
                name=name, description=description, is_active=True, updated_by=admin.id
            )
            session.add(service_type)
            await session.flush()
            for title, sequence, offset_days in templates:
                session.add(
                    TaskTemplate(
                        service_type_id=service_type.id,
                        title=title,
                        sequence=sequence,
                        default_offset_days=offset_days,
                        updated_by=admin.id,
                    )
                )
            service_types.append(service_type)
        await session.flush()

        monthly_gst, quarterly_tds, gst_registration = service_types
        today = date.today()
        task_counter = 0

        # Five monthly GST engagements, one per client, for the current month.
        for index, client in enumerate(clients):
            period_start, period_end = period_bounds(RecurrenceFrequency.MONTHLY, today)
            engagement = Engagement(
                client_id=client.id,
                service_type_id=monthly_gst.id,
                manager_id=managers[index % len(managers)].id,
                engagement_type=EngagementType.RECURRING,
                recurrence=RecurrenceFrequency.MONTHLY,
                start_date=period_start,
                period_start=period_start,
                period_end=period_end,
                auto_renew=True,
                updated_by=admin.id,
            )
            session.add(engagement)
            await session.flush()
            tasks = await generate_tasks_for_engagement(session, engagement)

            # Staff them and spread them across the workflow so the dashboard
            # has something to show.
            for offset, task in enumerate(tasks):
                member = members[(index + offset) % len(members)]
                if member.id == engagement.manager_id:
                    member = members[(index + offset + 1) % len(members)]
                task.assignee_id = member.id
                task.status = [
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                    TaskStatus.WAITING_FOR_CLIENT,
                    TaskStatus.READY_FOR_REVIEW,
                ][offset % 4]
                task_counter += 1

        # Two quarterly TDS engagements.
        for client in clients[:2]:
            period_start, period_end = period_bounds(RecurrenceFrequency.QUARTERLY, today)
            engagement = Engagement(
                client_id=client.id,
                service_type_id=quarterly_tds.id,
                manager_id=managers[0].id,
                engagement_type=EngagementType.RECURRING,
                recurrence=RecurrenceFrequency.QUARTERLY,
                start_date=period_start,
                period_start=period_start,
                period_end=period_end,
                auto_renew=True,
                updated_by=admin.id,
            )
            session.add(engagement)
            await session.flush()
            tasks = await generate_tasks_for_engagement(session, engagement)
            for offset, task in enumerate(tasks):
                task.assignee_id = members[offset % len(members)].id
                task.status = TaskStatus.ASSIGNED
                task_counter += 1

        # One one-time GST registration, with no period.
        engagement = Engagement(
            client_id=clients[4].id,
            service_type_id=gst_registration.id,
            manager_id=managers[1].id,
            engagement_type=EngagementType.ONE_TIME,
            recurrence=None,
            start_date=today,
            period_start=None,
            period_end=None,
            auto_renew=True,
            updated_by=admin.id,
        )
        session.add(engagement)
        await session.flush()
        tasks = await generate_tasks_for_engagement(session, engagement)
        for task in tasks:
            task.assignee_id = members[0].id
            task.status = TaskStatus.ASSIGNED
            task_counter += 1

        await session.commit()
        logger.info(
            "Seeded %d users, %d clients, %d service types and %d tasks.",
            len(USERS),
            len(CLIENTS),
            len(SERVICE_TYPES),
            task_counter,
        )


if __name__ == "__main__":
    asyncio.run(seed())
