# 0004. Handlers enqueue only

## Context

HTTP handlers run inline with the request/response cycle and are subject to
client timeouts. The payment provider's API can be slow or unavailable.
Calling it directly from a handler ties request latency to an external
service and makes retries (ADR-0003) harder to reason about, since a
handler that times out mid-call leaves the caller unsure whether the call
happened.

## Decision

HTTP handlers validate and enqueue. Only the worker talks to the payment
provider.

## Consequences

- Handlers are limited to: validating the request, writing/updating rows
  that represent intent (e.g. a pending charge or a queued event), and
  returning a response. They perform no outbound calls to the payment
  provider.
- All communication with the payment provider — charging, confirming,
  refunding — happens in the worker process, which owns retry and backoff
  behavior.
- This keeps handler latency bounded by the database, not by a third party.
