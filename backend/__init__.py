"""Veiled Eye backend as an installable package (``pip install`` / ``pipx install``).

The backend code uses flat imports (``from factories import ...``,
``modules.github.github_tasks``) exactly as it does inside the Docker image,
where this directory *is* the working directory.  When installed as the
``veiled_eye`` package we simply put the package directory on ``sys.path`` so those
imports keep working unchanged — Docker, tests and the pip package all share
one code layout.
"""

import os
import sys

__version__ = "3.1.0"

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
