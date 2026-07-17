# 0002. Money is integer cents

## Context

Floating-point arithmetic cannot represent most decimal fractions exactly.
Billing amounts that pass through float addition, multiplication, or
serialization accumulate rounding error, which is unacceptable when the
numbers represent money owed or charged to a customer.

## Decision

All monetary amounts are integer cents. Floats never touch money.

## Consequences

- Every money column in the database is `BIGINT`, storing cents.
- Every money field in application models (e.g. `Plan.amount`) is typed as
  an integer, never `float` or `Decimal` derived from a float.
- Formatting an amount for display (e.g. `$12.00`) happens only at the
  presentation edge, and only by dividing the integer cent value — the
  stored and transmitted value is always the integer.
- API request and response bodies carry amounts as integers, not decimal
  strings or floats.
