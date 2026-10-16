# Contributing

Issues and pull requests are welcome.

## Setup

```shell
just setup                 # venv with ruff + pre-commit, installs the git hooks
source .venv/bin/activate
pip install -e .           # the veiled-eye command, in development mode
```

## Before you open a pull request

```shell
just lint                  # ruff check + format check
cd backend && pytest -q    # the whole suite runs offline (HTTP is mocked)
```

## Adding a module

1. Create `backend/modules/<name>/<name>_tasks.py` with a `p_<name>(param)`
   function decorated with `@module_task(module_name="<name>")`. It returns
   the positional result list
   `[module, param, validation, raw, graphic, profile, timeline, (tasks)]`;
   `factories/module_kit.py` builds it for you for account-style sources.
2. Raise `Exception("warn: <message>")` for expected misses (not found, rate
   limited); any other exception is reported as a failure.
3. Register it in `backend/module_registry.py`. The worker imports every
   registered module automatically.
4. Add tests under `backend/tests/` with the HTTP layer mocked.

Only collect what a logged-out visitor can see, unless the user supplies their
own session for that source (see docs/COOKIES.md).

## Web UI

The UI is committed pre-built in `backend/frontend_dist`. Its theme and
behaviour live in `tools/ui_build/` (`veiled.css`, `veiled.js`); after editing
them run:

```shell
python tools/ui_build/patch.py backend/frontend_dist
```

## Commit messages

Short imperative subject (`Add Bluesky DID lookup`, `Fix phone parsing for TR
numbers`), details in the body when needed.
