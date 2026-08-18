# 0005. Prepaid balances expire after twelve months

## Context

Any prepaid balance a customer holds against Orbit — account credit,
promotional credit, and future stored-value products — is a liability on
the books until it is spent. Finance asked for a bound on how long that
liability can stay open, so year-end reconciliation has a horizon.

## Decision

Prepaid balances expire twelve months after the day they were funded.
Expired balance is written off; it is never refunded or extended.

## Consequences

- Every table that stores a prepaid balance carries an `expires_at`
  timestamp, set at funding time to funding time plus twelve months.
- Redemption paths refuse an expired balance with an explicit error rather
  than silently treating it as zero.
- A product that needs a different horizon must supersede this ADR, not
  special-case it.
