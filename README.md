# Orbit

Orbit is a subscription billing API: plans, customers, subscriptions, and the
charges and payment-provider webhooks that keep them paid. See
[`CONTEXT.md`](CONTEXT.md) for the domain vocabulary and
[`docs/adr/`](docs/adr/) for the rules the system is built to.

## Stack

Python 3.13, FastAPI, asyncpg, Postgres. Dependencies are managed with
[`uv`](https://docs.astral.sh/uv/).

## Running it

Install dependencies:

```bash
uv sync
```

Apply the database schema to a running Postgres instance, in order:

```bash
for f in migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
```

The billing tests exercise the idempotency guarantee (ADR-0001) against a
real Postgres database — start one before running the suite:

```bash
docker run -d --name orbit-postgres-test \
  -e POSTGRES_USER=orbit -e POSTGRES_PASSWORD=orbit -e POSTGRES_DB=orbit_test \
  -p 5433:5432 postgres:17
```

By default tests connect to `postgresql://orbit:orbit@localhost:5433/orbit_test`;
override with the `DATABASE_URL` environment variable to point elsewhere. Each
test resets the schema, so no manual migration step is needed.

Run the test suite:

```bash
uv run pytest
```

Lint and format:

```bash
uv run ruff check
uv run ruff format
uv run ty check src/
```
