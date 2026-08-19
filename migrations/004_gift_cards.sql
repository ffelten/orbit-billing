-- Stored-value gift cards a customer buys and redeems by code (see
-- docs/prd/gift-cards.md). Balances expire twelve months after funding,
-- like every prepaid balance (ADR-0005); expires_at is set by the
-- application at insert time rather than a DB default so it always
-- reflects funded_at + twelve months exactly.
CREATE TABLE gift_cards (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers (id),
    code TEXT NOT NULL UNIQUE,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    balance_cents BIGINT NOT NULL CHECK (balance_cents >= 0),
    funded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (balance_cents <= amount_cents),
    CHECK (expires_at > funded_at)
);

CREATE INDEX idx_gift_cards_customer_id ON gift_cards (customer_id);
