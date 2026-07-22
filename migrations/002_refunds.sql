-- Partial refunds against a charge (issue #9). Money is still BIGINT cents
-- (ADR-0002); this migration only adds the ledger and state to track them.

ALTER TABLE charges
    DROP CONSTRAINT charges_status_check,
    ADD CONSTRAINT charges_status_check
        CHECK (status IN ('pending', 'succeeded', 'failed', 'partially_refunded', 'refunded'));

ALTER TABLE charges
    ADD COLUMN refunded_amount_cents BIGINT NOT NULL DEFAULT 0 CHECK (refunded_amount_cents >= 0);

-- One row per refund recorded against a charge. `requested_amount_cents` is
-- what was asked for; `amount_cents` is what was actually credited after
-- prorating by unused days remaining in the charge's billing period.
CREATE TABLE refunds (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    charge_id BIGINT NOT NULL REFERENCES charges (id),
    requested_amount_cents BIGINT NOT NULL CHECK (requested_amount_cents > 0),
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    refunded_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_refunds_charge_id ON refunds (charge_id);
