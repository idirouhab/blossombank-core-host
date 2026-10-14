ALTER TABLE accrual ADD COLUMN settled_at TEXT;
CREATE TABLE accrual_carry (
    account_id TEXT PRIMARY KEY REFERENCES account_master(account_id),
    amount_micro INTEGER NOT NULL,
    through_date TEXT NOT NULL
);
CREATE INDEX unsettled_accrual ON accrual(account_id,settled_at,business_date);
