"""Runtime guards: HTTP default timeout, worker imports, task limits."""

from unittest.mock import patch

import pytest
import requests


def _send_reporting_timeout(self, request, **kwargs):
    raise requests.ConnectionError(repr(kwargs.get("timeout")))


@pytest.mark.parametrize(("given", "expected"), [(None, "default"), (3, "3")])
def test_requests_get_has_a_timeout(given, expected):
    from factories import http_defaults

    http_defaults.install()
    kwargs = {} if given is None else {"timeout": given}
    with (
        patch.object(requests.adapters.HTTPAdapter, "send", _send_reporting_timeout),
        pytest.raises(requests.ConnectionError) as exc,
    ):
        requests.get("http://example.invalid/", **kwargs)
    want = repr(http_defaults.DEFAULT_TIMEOUT) if expected == "default" else expected
    assert str(exc.value) == want


def test_every_registered_module_is_imported_by_the_worker():
    from celery_app import TASK_MODULES
    from module_registry import MODULE_REGISTRY

    for path, _ in MODULE_REGISTRY.values():
        assert path.rsplit(".", 1)[0] in TASK_MODULES, path


def test_worker_limits_are_set():
    from celery_app import celery

    assert celery.conf.task_soft_time_limit and celery.conf.task_time_limit
    assert celery.conf.result_expires
