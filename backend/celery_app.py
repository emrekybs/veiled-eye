"""Standalone Celery application — no Flask dependency.

This module replaces the old ``factories._celery.create_celery`` pattern
which unnecessarily coupled every Celery worker to a full Flask app.
Configuration is read directly from environment variables.
"""

import os

from celery import Celery
from factories import http_defaults
from module_registry import MODULE_REGISTRY

http_defaults.install()

# Task modules not reachable through the registry (special routes).
_EXTRA_TASK_MODULES = (
    "modules.dorks.dorks_tasks",
    "modules.tweetiment.tweetiment_tasks",
    "modules.twitter_comparison.twitter_info_tasks",
    "modules.twitter_comparison.twitter_comp_tasks",
)
# Derived from the registry so a registered module can never be missing on
# the worker (a missing import used to leave its tasks PENDING forever).
TASK_MODULES = tuple(
    sorted(
        {path.rsplit(".", 1)[0] for path, _ in MODULE_REGISTRY.values()}
        | set(_EXTRA_TASK_MODULES)
    )
)

_SOFT_LIMIT = int(os.environ.get("VEILED_TASK_SOFT_LIMIT", "900"))

celery = Celery(
    "veiled_eye",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
)

celery.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    imports=TASK_MODULES,
    # results are read once by the UI; keep Redis from growing forever
    result_expires=int(os.environ.get("VEILED_RESULT_EXPIRES", "86400")),
    # a hung source must not hold a worker slot forever
    task_soft_time_limit=_SOFT_LIMIT,
    task_time_limit=_SOFT_LIMIT + 60,
    # recycle children: maigret / headless scrapers grow memory over time
    worker_max_tasks_per_child=int(os.environ.get("VEILED_MAX_TASKS_PER_CHILD", "100")),
    worker_prefetch_multiplier=1,
    task_acks_late=False,
    broker_connection_retry_on_startup=True,
)

# `veiled-eye serve` without Redis (see cli.cmd_serve): the API and the worker
# share a folder-based queue (broker ``filesystem://``, results ``file://``).
_QUEUE_DIR = os.environ.get("VEILED_QUEUE_DIR")
if _QUEUE_DIR:
    _MESSAGES = os.path.join(_QUEUE_DIR, "messages")
    celery.conf.broker_transport_options = {
        "data_folder_in": _MESSAGES,
        "data_folder_out": _MESSAGES,
        "control_folder": os.path.join(_QUEUE_DIR, "control"),
        "store_processed": False,
        "polling_interval": 0.2,
    }
