# Orbit · the Hervé demo repository

[![CI](https://github.com/ffelten/orbit-billing/actions/workflows/ci.yml/badge.svg)](https://github.com/ffelten/orbit-billing/actions/workflows/ci.yml)

Orbit is a deliberately small subscription-billing service (plans,
customers, subscriptions, charges, provider webhooks, refunds). It exists
so you can see what [Hervé](https://herve.review) does with a codebase
where every line was written by an AI agent.

## Start here

- The pull request [Add gift cards](https://github.com/ffelten/orbit-billing/pull/20) — the feature this repo
  was built to demo.
- The issue [Gift cards](<PRD_ISSUE_URL>) — the PRD the PR was built from.
- [`docs/adr/`](docs/adr/) — four decisions the agents were told to respect.
- The [`entire/checkpoints/v1`](../../tree/entire/checkpoints/v1) branch —
  where the agent sessions behind every PR live. Hervé reads it; nothing is
  stored on Hervé's side.

## How it was built

Each PR is one or more Claude Code sessions, captured by `rv` (Hervé's CLI,
which sets up Entire). Commit trailers (`Entire-Checkpoint:`) point at the
session that produced each commit. CI runs the test suite and ruff on every
PR.

## Domain in one paragraph

A customer subscribes to a plan; each period produces a charge; the payment
provider confirms it through a webhook. Amounts are integer cents. Gift
cards are prepaid balances redeemable at checkout.

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
