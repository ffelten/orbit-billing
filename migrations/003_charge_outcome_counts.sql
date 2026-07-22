-- Per-day counters of charge outcomes, incremented transactionally alongside
-- the charge transition that produced them (see orbit.billing.metrics).
-- Backs GET /metrics/charges.
CREATE TABLE charge_outcome_counts (
    day DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    count BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day, status)
);
