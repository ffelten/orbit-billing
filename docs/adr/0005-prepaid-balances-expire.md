# 0005. Account and promotional credit expires after twelve months

## Context

Account credit and promotional credit a customer holds against Orbit is a
liability on the books until it is spent. Finance asked for a bound on how
long that liability can stay open, so year-end reconciliation has a horizon.

Stored-value products a customer *buys* — gift cards, vouchers — are out of
scope: their expiry policy is set by the product's own PRD, not this ADR.

## Decision

Account and promotional credit expires twelve months after the day it was
funded. Expired credit is written off; it is never refunded or extended.

## Consequences

- Every table that stores account or promotional credit carries an
  `expires_at` timestamp, set at funding time to funding time plus twelve
  months.
- Redemption paths refuse expired credit with an explicit error rather than
  silently treating it as zero.
- A stored-value product a customer buys (gift cards, vouchers) defines its
  own expiry in its PRD; it is not governed by this ADR.
