# Task & Engagement Management — Backend

FastAPI service for managing client engagements, the tasks generated from
them, and the review workflow those tasks move through.

## Requirements

- Python 3.10+
- PostgreSQL 14+

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Create two databases on your PostgreSQL server — one for the app, one for the
test suite (if they already exist on your machine, skip this step):

```bash
createdb task_management
createdb task_management_test
```

Then create `backend/.env` with your connection details:

```bash
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/db_name
TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/db_name_test
JWT_SECRET_KEY=change-me-to-a-long-random-string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
RECURRENCE_LEAD_DAYS=3
CORS_ORIGINS=["http://localhost:5173"]
```

Both `DATABASE_URL` and `TEST_DATABASE_URL` are required: the test suite
refuses to start without `TEST_DATABASE_URL` set, deliberately, so a test run
can never truncate the development database. Point `HOST`/`PORT` at whichever
Postgres server hosts your two databases — if you run several Postgres
instances locally (for example via Docker alongside other clusters on your
machine), make sure this points at the one that actually has
`task_management` and `task_management_test`.

Apply migrations and load demo data:

```bash
alembic upgrade head
python seed.py
```

## Running

```bash
uvicorn app.main:app --reload
```

Interactive API documentation: http://localhost:8000/docs

## Tests

```bash
pytest -v
```

Tests run against `TEST_DATABASE_URL`, a real PostgreSQL database rather than
SQLite, because the triggers, partial unique indexes and check constraints the
design relies on do not exist in SQLite. The suite refuses to run at all if
`TEST_DATABASE_URL` is not set, so it can never accidentally run against
(and truncate) the development database.

## Demo credentials

All seeded accounts use the password `Demo1234!`.

| Role | Email |
|---|---|
| Admin | admin@example.com |
| Manager | priya.manager@example.com |
| Manager | rahul.manager@example.com |
| Team member | sara.member@example.com |
| Team member | omar.member@example.com |
| Team member | lena.member@example.com |
| Team member | kofi.member@example.com |
