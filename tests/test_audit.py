import uuid

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_insert_writes_an_audit_row(db_session):
    client_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO client (id, name, is_active, created_at, updated_at) "
            "VALUES (:id, 'Acme Ltd', true, now(), now())"
        ),
        {"id": client_id},
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT operation, new_data FROM client_audit WHERE record_id = :id"),
        {"id": client_id},
    )
    row = result.one()
    assert row.operation == "INSERT"
    assert row.new_data["name"] == "Acme Ltd"


@pytest.mark.asyncio
async def test_update_records_the_acting_user(db_session, admin_user):
    client_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO client (id, name, is_active, created_at, updated_at) "
            "VALUES (:id, 'Acme Ltd', true, now(), now())"
        ),
        {"id": client_id},
    )
    await db_session.execute(
        text("UPDATE client SET name = 'Acme Limited', updated_by = :actor WHERE id = :id"),
        {"id": client_id, "actor": admin_user.id},
    )
    await db_session.commit()

    result = await db_session.execute(
        text(
            "SELECT changed_by, old_data, new_data FROM client_audit "
            "WHERE record_id = :id AND operation = 'UPDATE'"
        ),
        {"id": client_id},
    )
    row = result.one()
    assert row.changed_by == admin_user.id
    assert row.old_data["name"] == "Acme Ltd"
    assert row.new_data["name"] == "Acme Limited"
