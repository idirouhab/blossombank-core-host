       >>SOURCE FORMAT FREE
identification division.
program-id. LEGACYAMT.
data division.
working-storage section.
01 request-line pic x(40).
01 display-amount pic s9(11)v99 comp-3.
01 minor-amount pic s9(13) comp-3.
01 output-amount pic -(13)9.
procedure division.
main.
    accept request-line
    if function test-numval(request-line) not = 0
        display 'BAD_AMOUNT|Invalid amount in clearing card'
        stop run
    end-if
    compute display-amount rounded = function numval(request-line)
    compute minor-amount = display-amount * 100
    move minor-amount to output-amount
    display 'OK|' function trim(output-amount)
    goback.
