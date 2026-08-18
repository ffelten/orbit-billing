-- Prepaid balances customers buy and give as a code to redeem at checkout
-- (docs/prd/gift-cards.md). Amounts are BIGINT cents (ADR-0002). Gift cards
-- never expire (see ADR-0005: stored-value products set their own expiry).
CREATE TABLE gift_cards (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    purchaser_customer_id BIGINT NOT NULL REFERENCES customers (id),
    face_value_cents BIGINT NOT NULL CHECK (face_value_cents >= 0),
    balance_cents BIGINT NOT NULL CHECK (balance_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (balance_cents <= face_value_cents)
);

CREATE INDEX idx_gift_cards_purchaser_customer_id ON gift_cards (purchaser_customer_id);
