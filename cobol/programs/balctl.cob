       >>SOURCE FORMAT FREE
identification division.
program-id. BALCTL.
data division.
working-storage section.
01 request-line pic x(80).
01 input-ccy pic x(3).
01 amount-text pic x(24).
01 item-index binary-long.
01 record-count binary-long value 0.
01 output-count pic 9(5).
01 output-total pic -(17)9.
01 found-flag pic x.
copy 'CCYREG.cpy'.
procedure division.
main.
    move 'EUR' to WS-CCY(1)
    move 'USD' to WS-CCY(2)
    move 'GBP' to WS-CCY(3)
    move 'JPY' to WS-CCY(4)
    move 'KWD' to WS-CCY(5)
    perform until record-count > 10000
        move spaces to request-line
        accept request-line
        if request-line = 'END' exit perform end-if
        if request-line = spaces
            display 'INVALID_CONTROL|Missing end of input'
            stop run
        end-if
        unstring request-line delimited by '|'
            into input-ccy amount-text
        end-unstring
        move 'N' to found-flag
        perform varying item-index from 1 by 1 until item-index > 5
            if input-ccy = WS-CCY(item-index)
                add function numval(amount-text) to WS-TOTAL(item-index)
                move 'Y' to found-flag
            end-if
        end-perform
        if found-flag = 'N'
            display 'UNKNOWN_CURRENCY|' input-ccy
            stop run
        end-if
        add 1 to record-count
    end-perform
    perform varying item-index from 1 by 1 until item-index > 5
        if WS-TOTAL(item-index) not = 0
            move WS-TOTAL(item-index) to output-total
            display 'UNBALANCED|' WS-CCY(item-index) '|'
                function trim(output-total)
            stop run
        end-if
    end-perform
    move record-count to output-count
    display 'OK|' output-count
    goback.
