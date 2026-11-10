# Pull request CI

The `.github/workflows/pr-quality.yml` workflow runs on pull requests targeting `main`.
It uses Python 3.12 and a disposable PostgreSQL 17 service. No production database
or VPS is used. The PostgreSQL password and database exist only inside the CI runner.

Checks fail the PR job on nonzero exit: diff whitespace, Ruff, the full SQLite
pytest suite, a single Alembic head, migration upgrade on empty PostgreSQL, and
mandatory PostgreSQL smoke tests. The smoke tests require a reachable local
PostgreSQL instance with the `amp_ci` database and verify that migrations
created the schema and version table. They must not silently skip in CI.

## Run locally

Install dependencies from `requirements.txt`, plus `pydantic-settings`,
`httpx`, `pytest`, and `ruff` (Python 3.12).

```sh
python -m ruff check .
python -m pytest -q --ignore=tests/test_ci_postgres.py
python -m alembic heads
```

For the PostgreSQL checks, start a **disposable local** PostgreSQL 17 instance
with database `amp_ci` and user `amp_ci`. Set `CI_POSTGRES_URL` to its
local URL, and run `DATABASE_URL="$CI_POSTGRES_URL" python -m alembic upgrade head`
followed by `AMP_REQUIRE_POSTGRES_TESTS=1 python -m pytest -q -rs tests/test_ci_postgres.py`.
Never point either variable at production. The SQLite suite's `tests/conftest.py`
always creates its own temporary database.

## Troubleshooting and adding tests

A failed Ruff step indicates lint issues; pytest failures show the failing
assertion and traceback. An Alembic head-count failure means divergent migration
heads; migration failures indicate incompatible migrations or schema. PostgreSQL
connection errors fail the mandatory smoke tests rather than skipping them.

Add unit tests under `tests/test_*.py`; they run automatically in the SQLite
suite. Add PostgreSQL-specific tests to `tests/test_ci_postgres.py` or extend
the mandatory PostgreSQL command in the workflow. Do not use real credentials,
network publishing, or production resources in tests.
