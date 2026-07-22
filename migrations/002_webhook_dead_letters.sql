-- Terminal sink for webhook events that exhaust all retry attempts (ADR-0003).
-- Support uses GET /webhooks/dead-letter to see what was dropped instead of
-- having to go digging through logs.
CREATE TABLE webhook_dead_letters (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_event_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    error_message TEXT NOT NULL,
    attempts INT NOT NULL,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_webhook_dead_letters_failed_at ON webhook_dead_letters (failed_at DESC);
