CREATE TABLE day_control (
    business_date TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('OPEN','CLOSED')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    cutoff_sequence INTEGER,
    control_hash TEXT
);
CREATE TABLE balance_snapshot (
    business_date TEXT NOT NULL REFERENCES day_control(business_date),
    account_id TEXT NOT NULL REFERENCES account_master(account_id),
    currency TEXT NOT NULL,
    balance_minor INTEGER NOT NULL,
    debit_turnover INTEGER NOT NULL,
    credit_turnover INTEGER NOT NULL,
    PRIMARY KEY(business_date,account_id)
);
CREATE TABLE accrual (
    business_date TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES account_master(account_id),
    currency TEXT NOT NULL,
    annual_bps INTEGER NOT NULL,
    balance_minor INTEGER NOT NULL,
    amount_micro INTEGER NOT NULL,
    settlement_posting TEXT REFERENCES posting(posting_id),
    PRIMARY KEY(business_date,account_id)
);
CREATE TABLE batch_run (
    run_id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    state TEXT NOT NULL CHECK(state IN ('RUNNING','COMPLETED','FAILED')),
    accepted_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    report_json TEXT,
    UNIQUE(job_name,input_digest)
);
CREATE TABLE batch_reject (
    run_id TEXT NOT NULL REFERENCES batch_run(run_id),
    line_number INTEGER NOT NULL,
    input_record TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(run_id,line_number)
);
