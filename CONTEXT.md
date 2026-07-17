# Orbit — Domain Language

Orbit is a subscription billing API. This document defines the vocabulary used
throughout the code, docs, and commit messages. Use these terms precisely.

- **Plan** — a named price point. Has an amount (integer cents) and an
  interval (`monthly` or `yearly`). Plans do not change once subscriptions
  reference them; a price change is a new plan.

- **Customer** — someone who can hold subscriptions.

- **Subscription** — a customer on a plan, with a current period (start and
  end). A subscription produces one charge per period.

- **Charge** — one unit of money owed for one subscription period. States:
  `pending` → `succeeded` | `failed`. A charge is created once per period and
  is never duplicated by retries (see ADR-0001).

- **Attempt** — one try at settling a charge. A charge may have many
  attempts; an attempt belongs to exactly one charge.

- **Event** — an inbound webhook from the payment provider, reporting the
  outcome of an attempt to charge a customer.

See `docs/adr/` for the rules that govern how these concepts interact.
