       >>SOURCE FORMAT FREE
identification division.
program-id. INTRCALC.
data division.
working-storage section.
01 request-line pic x(120).
01 balance-text pic x(24).
01 rate-text pic x(8).
01 days-text pic x(4).
01 basis-text pic x(4).
01 balance-minor pic s9(15) comp-3.
01 rate-bps pic 9(5) comp-3.
01 accrual-days pic 9(3) comp-3.
01 basis-days pic 9(3) comp-3.
01 calculation-result pic s9(21)v9(8) comp-3.
01 accrual-micro pic s9(21) comp-3.
01 output-accrual pic -(21)9.
procedure division.
main.
    accept request-line
    unstring request-line delimited by '|'
        into balance-text rate-text days-text basis-text
    end-unstring
    compute balance-minor = function numval(balance-text)
    compute rate-bps = function numval(rate-text)
    compute accrual-days = function numval(days-text)
    compute basis-days = function numval(basis-text)
    if basis-days not = 360 and basis-days not = 365
        display 'BAD_BASIS|Only ACT360 or ACT365 supported'
        stop run
    end-if
    if accrual-days = 0 or accrual-days > 366
        display 'BAD_PERIOD|Accrual days outside supported range'
        stop run
    end-if
    compute calculation-result = balance-minor * rate-bps *
        accrual-days * 1000000 / 10000 / basis-days
    compute accrual-micro rounded = calculation-result
    move accrual-micro to output-accrual
    display 'OK|' function trim(output-accrual)
    goback.
