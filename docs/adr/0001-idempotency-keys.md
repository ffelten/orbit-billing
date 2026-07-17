# 0001. Idempotency keys

## Context

The payment provider retries webhook delivery on timeout or non-2xx
responses. Without a stable way to recognize a retry, a redelivered webhook
for an event we already processed would be treated as new work, and could
produce a second charge for the same subscription period.

## Decision

A charge's idempotency key is derived from the payment provider's event ID.
It MUST NOT be regenerated between retry attempts. Two attempts at the same
event are the same charge, never two charges.

## Consequences

- The `charges` table (via `processed_events`) enforces a unique constraint
  on the provider event ID, so a duplicate delivery is rejected at the
  database level, not just in application logic.
- Handlers must extract the event ID before doing anything else, and use it
  as the sole basis for deciding whether a charge already exists.
- Idempotency keys are never generated from timestamps, request IDs, or
  other values that change between retries of the same event.
