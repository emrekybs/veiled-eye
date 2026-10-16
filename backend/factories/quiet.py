"""Thread-local stdout/stderr silencing.

``contextlib.redirect_stdout`` swaps ``sys.stdout`` for the WHOLE process, so
when the ``veiled-eye scan`` CLI runs modules in parallel threads, one module
silencing a chatty library would also swallow the CLI's own output (and
another thread's).  ``silenced()`` instead installs (once) a proxy stream
that drops writes only from the thread that asked for silence.
"""

from __future__ import annotations

import contextlib
import sys
import threading

_state = threading.local()
_install_lock = threading.Lock()


class _ThreadAwareStream:
    def __init__(self, real):
        self._real = real

    def write(self, data):
        if getattr(_state, "depth", 0) > 0:
            return len(data) if isinstance(data, str) else 0
        return self._real.write(data)

    def flush(self):
        if getattr(_state, "depth", 0) > 0:
            return None
        return self._real.flush()

    def isatty(self):
        if getattr(_state, "depth", 0) > 0:
            return False
        return self._real.isatty()

    def __getattr__(self, name):
        return getattr(self._real, name)


def _install() -> None:
    with _install_lock:
        if not isinstance(sys.stdout, _ThreadAwareStream):
            sys.stdout = _ThreadAwareStream(sys.stdout)
        if not isinstance(sys.stderr, _ThreadAwareStream):
            sys.stderr = _ThreadAwareStream(sys.stderr)


@contextlib.contextmanager
def silenced():
    """Drop stdout/stderr writes made by the current thread."""
    _install()
    _state.depth = getattr(_state, "depth", 0) + 1
    try:
        yield
    finally:
        _state.depth -= 1
