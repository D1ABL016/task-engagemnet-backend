import pytest


def test_scheduler_registers_the_recurrence_job():
    from app.jobs.scheduler import create_scheduler

    scheduler = create_scheduler()
    job = scheduler.get_job("daily_recurrence_generation")
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True


@pytest.mark.asyncio
async def test_job_runs_without_error_on_an_empty_database():
    from app.jobs.recurrence_job import run_daily_recurrence_job

    await run_daily_recurrence_job()
