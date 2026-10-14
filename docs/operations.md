# BLSONL1 operating note

## Start and stop

Build once before starting a new checkout. `run.sh` builds missing executables;
after changing sources, explicitly run `build.sh`. Stop the foreground region
with Ctrl-C or terminate its process. SQLite handles an interrupted transaction
without exposing its partial entries.

Keep the database, its `-wal` file and its `-shm` file together while running.
For a copy of live state, use the `backup` command instead of copying the main
database alone. A backup can be reopened by passing `--database PATH` before
the command name.

## Daily accounting

The business date is an accounting control, separate from the wall clock.
Installation opens the current UTC date. Dates never advance automatically.

1. Run `reconcile` and resolve any control break.
2. Run `expire-holds`.
3. Run `close-day YYYY-MM-DD` for the current business date.
4. Run `accrue YYYY-MM-DD` for that closed date.
5. Export the account unload and take a backup.
6. Run `open-day YYYY-MM-DD` with a later date.
7. Run `settle YYYY-MM-DD` when the accrual period is due for settlement.

Closing records balances, debit and credit turnover, last journal sequence, and
a digest. Repeating a completed close returns its recorded result. A closed
region rejects new postings until another day opens. Replays of existing
postings remain readable.

Interest is accrued using the product rate and the closed-day balance. Carry is
stored in millionths of the account's minor unit, preserving fractions between
settlements. Settlement and its accrual markers commit together. A rejected
account posting aborts the settlement transaction so the run can be retried.

## Clearing

`import-clearing` takes UTF-8 CSV with these columns:

```text
reference,debtor,creditor,currency,amount,narrative
```

The file digest identifies a job. Each line has an independent external
reference. Accepted lines commit independently; rejects are retained with line
numbers. A completed file returns its previous report when submitted again.
If a process is terminated before recording its job completion, inspect the
journal and job state with `batch-runs`, then run `recover-batch RUN_ID` and
resubmit the same file. Do not reset a job whose worker is still active.

The CLR021 amount card is processed by the local host executable. Operational
acceptance must compare its output with the source instruction totals.

## Control breaks

`reconcile` compares current balances with opening balances plus journal
movements, checks every posting by currency, verifies the stored running
balances, and runs SQLite integrity checks. It returns exit status 2 if breaks
are present. Do not update or delete journal rows to repair a business error.

The account master is not a substitute for the journal feed. Likewise, an
account unload is a cutoff snapshot; it is not an incremental movement file.

## Account unload

`unload-accounts PATH` writes fixed 84-byte AC01 records and a JSON manifest.
The record uses packed decimals and includes the office account identifiers.
The manifest gives the business date, record count, cutoff sequence and SHA-256.
The operation writes a temporary dataset and renames it after checking its
length and COBOL control count. Keep the manifest alongside the dataset.

## Diagnostics

- `HOST_PROGRAM_UNAVAILABLE`: verify the executable exists and GnuCOBOL runtime libraries are available.
- `REGION_CLOSED`: inspect `GET /v1/admin/days`; open the next date after scheduled close work.
- `REFERENCE_CONFLICT`: compare the original booking through reference lookup before retrying.
- `CONTROL_BREAK`: inspect reconciliation output and restore from a consistent backup if required.
- `database is locked`: check for a long-running operator write; the writer waits up to 15 seconds.

HTTP request logs include method, path, result code and peer address. Audit
events are stored in the database. Runtime files are not source artefacts.
