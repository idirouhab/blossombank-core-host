CREATE TABLE posting (
    posting_id TEXT PRIMARY KEY,
    external_reference TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    booked_at TEXT NOT NULL,
    business_date TEXT NOT NULL,
    narrative TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'ONLINE',
    reversal_of TEXT REFERENCES posting(posting_id),
    UNIQUE(reversal_of)
);
CREATE TABLE journal (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id TEXT NOT NULL REFERENCES posting(posting_id),
    ordinal INTEGER NOT NULL,
    account_id TEXT NOT NULL REFERENCES account_master(account_id),
    currency TEXT NOT NULL,
    delta_minor INTEGER NOT NULL,
    resulting_balance INTEGER NOT NULL,
    UNIQUE(posting_id,ordinal)
);
CREATE INDEX journal_account ON journal(account_id,sequence);
CREATE INDEX journal_posting ON journal(posting_id,ordinal);
CREATE TABLE audit_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    happened_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE TRIGGER journal_immutable_update BEFORE UPDATE ON journal
BEGIN SELECT RAISE(ABORT,'journal is immutable'); END;
CREATE TRIGGER journal_immutable_delete BEFORE DELETE ON journal
BEGIN SELECT RAISE(ABORT,'journal is immutable'); END;
