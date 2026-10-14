       >>SOURCE FORMAT FREE
identification division.
program-id. ENTRYCHK.
environment division.
configuration section.
repository. function all intrinsic.
data division.
working-storage section.
01 request-line pic x(400).
01 input-status pic x(8).
01 input-internal pic x.
01 input-ccy pic x(3).
01 account-ccy pic x(3).
01 exponent-text pic x(3).
01 ledger-text pic x(20).
01 available-text pic x(20).
01 delta-text pic x(20).
01 debit-allowed pic x.
01 account-balance pic s9(15) comp-3.
01 available-balance pic s9(15) comp-3.
01 posting-delta pic s9(15) comp-3.
01 ending-balance pic s9(16) comp-3.
01 output-balance pic -(16)9.
copy 'CCYREG.cpy'.
procedure division.
main.
    accept request-line
    unstring request-line delimited by '|'
        into input-status input-internal input-ccy account-ccy
        exponent-text ledger-text available-text delta-text debit-allowed
    end-unstring
    if input-ccy not = account-ccy
        display 'CURRENCY_MISMATCH|Entry currency differs from account'
        stop run
    end-if
    evaluate input-ccy
        when 'EUR' when 'USD' when 'GBP'
            move 2 to WS-CURRENCY-EXPONENT
        when 'JPY' move 0 to WS-CURRENCY-EXPONENT
        when 'KWD' move 3 to WS-CURRENCY-EXPONENT
        when other
            display 'UNKNOWN_CURRENCY|Currency absent from online register'
            stop run
    end-evaluate
    if function numval(exponent-text) not = WS-CURRENCY-EXPONENT
        display 'EXPONENT_CONFLICT|Online currency scale mismatch'
        stop run
    end-if
    compute account-balance = function numval(ledger-text)
    compute available-balance = function numval(available-text)
    compute posting-delta = function numval(delta-text)
    if input-status = 'CLOSED'
        display 'ACCOUNT_CLOSED|Account no longer accepts postings'
        stop run
    end-if
    if posting-delta < 0
        if input-status = 'FROZEN' or debit-allowed not = 'Y'
            display 'DEBIT_BLOCKED|Account is blocked for debit'
            stop run
        end-if
        if input-internal not = 'Y' and
            available-balance + posting-delta < 0
            display 'INSUFFICIENT_FUNDS|Available balance is insufficient'
            stop run
        end-if
    end-if
    compute ending-balance = account-balance + posting-delta
    if ending-balance > 999999999999 or ending-balance < -999999999999
        display 'BALANCE_OVERFLOW|Account balance exceeds online field'
        stop run
    end-if
    move ending-balance to output-balance
    display 'OK|' function trim(output-balance)
    goback.
