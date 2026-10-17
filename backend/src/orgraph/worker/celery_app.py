"""Celery application.

worker:  celery -A orgraph.worker.celery_app worker --loglevel=info
beat:    celery -A orgraph.worker.celery_app beat --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from ..config import get_settings

settings = get_settings()

celery_app = Celery(
    "orgraph",
    broker=settings.redis_url,
    backend=settings.celery_result_backend,
    include=["orgraph.worker.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_eager,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Run state lives in the store, so results are only kept if a backend is configured.
    task_ignore_result=settings.celery_result_backend is None,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=15 * 60,
    task_time_limit=16 * 60,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "scheduler-tick": {
            "task": "orgraph.scheduler_tick",
            "schedule": float(settings.scheduler_tick_seconds),
            # A tick that waited longer than one interval is stale; the next one covers it.
            "options": {"expires": float(settings.scheduler_tick_seconds)},
        }
    },
)

app = celery_app
