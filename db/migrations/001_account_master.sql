CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    installed_at TEXT NOT NULL
);
CREATE TABLE account_master (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    currency TEXT NOT NULL CHECK(length(currency)=3),
    product_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','FROZEN','CLOSED')),
    ledger_minor INTEGER NOT NULL,
    opening_minor INTEGER NOT NULL,
    overdraft_minor INTEGER NOT NULL DEFAULT 0 CHECK(overdraft_minor >= 0),
    branch_code TEXT NOT NULL DEFAULT '0042',
    opened_on TEXT NOT NULL,
    last_activity TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    debit_block TEXT NOT NULL DEFAULT '',
    internal INTEGER NOT NULL DEFAULT 0 CHECK(internal IN (0,1))
);
CREATE INDEX account_customer ON account_master(customer_id, account_id);
CREATE TABLE account_alias (
    alias TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES account_master(account_id),
    channel TEXT NOT NULL,
    valid_until TEXT
);
CREATE TABLE customer_flags (
    customer_id TEXT PRIMARY KEY,
    residence_country TEXT NOT NULL DEFAULT 'ZZ',
    statement_language TEXT NOT NULL DEFAULT 'en',
    tax_exempt INTEGER NOT NULL DEFAULT 0,
    account_group TEXT NOT NULL DEFAULT 'RETAIL'
);
