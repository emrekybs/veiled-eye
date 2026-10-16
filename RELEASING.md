# Releasing to PyPI

`pip install veiled-eye` / `pipx install veiled-eye` install from PyPI.

## One-time setup

1. Create the project on PyPI with a *trusted publisher*: pypi.org →
   Account settings → Publishing → Add a new pending publisher →
   GitHub, owner `emrekybs`, repository `veiled-eye`, workflow `publish.yml`,
   environment `pypi`.
2. In the GitHub repository create the environment `pypi`
   (Settings → Environments).

## Each release

1. Bump `version` in `pyproject.toml` and `VERSION` in `backend/veiled_meta.py`.
2. Rebuild the web UI if it changed:
   `python tools/ui_build/patch.py backend/frontend_dist` (on a fresh upstream build).
3. Tag and publish a GitHub release. `.github/workflows/publish.yml` builds
   the wheel and sdist, runs `twine check` and uploads to PyPI.

Manual alternative:

```shell
python -m pip install --upgrade build twine
python -m build
python -m twine upload dist/*
```
