# Orbit — Domain Language

This repo is the [Hervé](https://app.herve.review) demo: every line was
written by an AI agent, guided by this document and the ADRs it links to.

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

- **Gift card** — a prepaid balance, identified by a code, that a customer
  buys and anyone holding the code can redeem at checkout. Redeemable
  partially; the remainder stays on the card. Never expires (see ADR-0005:
  stored-value products a customer buys set their own expiry).

See `docs/adr/` for the rules that govern how these concepts interact.
