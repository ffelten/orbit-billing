-- Orbit initial schema.
-- All monetary amounts are BIGINT cents (ADR-0002). Floats never touch money.

CREATE TABLE plans (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    interval TEXT NOT NULL CHECK (interval IN ('monthly', 'yearly')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE customers (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers (id),
    plan_id BIGINT NOT NULL REFERENCES plans (id),
    status TEXT NOT NULL CHECK (status IN ('active', 'canceled')),
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (current_period_end > current_period_start)
);

CREATE INDEX idx_subscriptions_customer_id ON subscriptions (customer_id);

-- One charge per subscription period. The idempotency key is derived from
-- the payment provider's event ID and MUST NOT be regenerated between retry
-- attempts (ADR-0001): two attempts at the same event are the same charge.
CREATE TABLE charges (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id BIGINT NOT NULL REFERENCES subscriptions (id),
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'failed')),
    idempotency_key TEXT NOT NULL UNIQUE,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_end > period_start)
);

CREATE INDEX idx_charges_subscription_id ON charges (subscription_id);

-- One try at settling a charge. A charge may have many attempts.
CREATE TABLE attempts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    charge_id BIGINT NOT NULL REFERENCES charges (id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
    provider_reference TEXT,
    error_message TEXT,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_attempts_charge_id ON attempts (charge_id);

-- Inbound webhooks from the payment provider. The unique constraint on
-- provider_event_id is what makes ADR-0001 enforceable at the database
-- level: a redelivered webhook for an already-processed event is rejected
-- by this constraint rather than by application logic alone.
CREATE TABLE processed_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_event_id TEXT NOT NULL UNIQUE,
    charge_id BIGINT REFERENCES charges (id),
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
