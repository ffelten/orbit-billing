# 0003. Retry policy

## Context

Webhook processing can fail transiently (network errors, provider outages,
temporary database unavailability). Retrying gives transient failures a
chance to succeed, but unbounded retries can mask permanent failures and
retries must never be allowed to create duplicate financial records.

## Decision

Webhook processing retries at most 5 times with exponential backoff. A retry
MUST NOT create a new charge.

## Consequences

- The worker tracks attempt count per event and stops retrying after 5
  attempts, surfacing the event as failed for manual investigation.
- Backoff between attempts grows exponentially, to avoid hammering a
  degraded payment provider or database.
- Because retries reuse the same idempotency key (ADR-0001), a retry that
  reaches an already-created charge updates or attempts that charge — it
  never inserts a second one.
