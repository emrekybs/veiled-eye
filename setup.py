"""Package discovery for ``pip install`` / ``pipx install``.

``backend/`` is installed as the ``veiled_eye`` package.  Every sub-folder (each
OSINT module, factories, routers) is picked up automatically, so adding a new
module under ``backend/modules/<name>/`` needs no packaging change.
Metadata lives in pyproject.toml.
"""

from setuptools import find_namespace_packages, setup

_EXCLUDE = [
    "tests",
    "tests.*",
    "cookies",
    "cookies.*",
    "outputs",
    "outputs.*",
    "*__pycache__*",
]

packages = ["veiled_eye"] + [
    f"veiled_eye.{pkg}" for pkg in find_namespace_packages("backend", exclude=_EXCLUDE)
]

setup(packages=packages, package_dir={"veiled_eye": "backend"})
