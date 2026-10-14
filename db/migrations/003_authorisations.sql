CREATE TABLE hold (
    hold_id TEXT PRIMARY KEY,
    external_reference TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL REFERENCES account_master(account_id),
    currency TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','RELEASED','EXPIRED','CAPTURED')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    posting_id TEXT REFERENCES posting(posting_id)
);
CREATE INDEX hold_account ON hold(account_id,status,expires_at);
CREATE TABLE lien (
    lien_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES account_master(account_id),
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    authority_reference TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    released_at TEXT
);
