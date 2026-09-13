"""audit tables and triggers

Revision ID: 4e1c285449b3
Revises: 74686c0ba6bc
Create Date: 2026-09-13 21:44:32.069470

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e1c285449b3'
down_revision: Union[str, None] = '74686c0ba6bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AUDITED_TABLES = [
    "client",
    "service_type",
    "task_template",
    "engagement",
    "task",
]

AUDIT_FUNCTION = """
CREATE OR REPLACE FUNCTION record_audit() RETURNS TRIGGER AS $$
DECLARE
    actor UUID;
BEGIN
    IF (TG_OP = 'DELETE') THEN
        actor := OLD.updated_by;
        EXECUTE format(
            'INSERT INTO %I (audit_id, record_id, operation, changed_by, changed_at, old_data, new_data)
             VALUES (gen_random_uuid(), $1, $2, $3, now(), $4, NULL)',
            TG_TABLE_NAME || '_audit'
        ) USING OLD.id, TG_OP, actor, to_jsonb(OLD);
        RETURN OLD;
    ELSE
        actor := NEW.updated_by;
        EXECUTE format(
            'INSERT INTO %I (audit_id, record_id, operation, changed_by, changed_at, old_data, new_data)
             VALUES (gen_random_uuid(), $1, $2, $3, now(), $4, $5)',
            TG_TABLE_NAME || '_audit'
        ) USING NEW.id, TG_OP, actor,
                CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) ELSE NULL END,
                to_jsonb(NEW);
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute(AUDIT_FUNCTION)

    for table_name in AUDITED_TABLES:
        op.execute(
            f"""
            CREATE TABLE {table_name}_audit (
                audit_id   UUID PRIMARY KEY,
                record_id  UUID NOT NULL,
                operation  TEXT NOT NULL,
                changed_by UUID NULL,
                changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                old_data   JSONB NULL,
                new_data   JSONB NULL
            )
            """
        )
        op.execute(
            f"CREATE INDEX {table_name}_audit_record_idx "
            f"ON {table_name}_audit (record_id, changed_at DESC)"
        )
        op.execute(
            f"CREATE TRIGGER {table_name}_audit_trigger "
            f"AFTER INSERT OR UPDATE OR DELETE ON {table_name} "
            f"FOR EACH ROW EXECUTE FUNCTION record_audit()"
        )


def downgrade() -> None:
    for table_name in AUDITED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_audit_trigger ON {table_name}")
        op.execute(f"DROP TABLE IF EXISTS {table_name}_audit")
    op.execute("DROP FUNCTION IF EXISTS record_audit()")
