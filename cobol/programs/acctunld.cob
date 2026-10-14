       >>SOURCE FORMAT FREE
identification division.
program-id. ACCTUNLD.
environment division.
input-output section.
file-control.
    select account-output assign to output-path
        organization is sequential
        access mode is sequential
        file status is output-status.
data division.
file section.
fd account-output
    recording mode is F.
copy 'ACCTREC.cpy'.
working-storage section.
01 output-path pic x(512).
01 output-status pic xx.
01 input-record pic x(300).
01 account-text pic x(10).
01 customer-text pic x(12).
01 product-text pic x(4).
01 currency-text pic x(3).
01 status-text pic x.
01 balance-text pic x(20).
01 hold-text pic x(20).
01 credit-text pic x(20).
01 date-text pic x(8).
01 sequence-text pic x(12).
01 branch-text pic x(4).
01 record-count pic 9(9) comp-3 value 0.
01 output-count pic 9(9).
procedure division.
main.
    accept output-path from command-line
    if output-path = spaces
        display 'FILE_ERROR|Output dataset not supplied'
        move 12 to return-code
        stop run
    end-if
    open output account-output
    if output-status not = '00'
        display 'FILE_ERROR|OPEN failed ' output-status
        move 12 to return-code
        stop run
    end-if
    perform until record-count > 999999998
        move spaces to input-record
        accept input-record
        if input-record = 'END' exit perform end-if
        if input-record = spaces
            close account-output
            display 'INPUT_ERROR|Missing end marker'
            move 8 to return-code
            stop run
        end-if
        perform write-account
    end-perform
    close account-output
    if output-status not = '00'
        display 'FILE_ERROR|CLOSE failed ' output-status
        move 12 to return-code
        stop run
    end-if
    move record-count to output-count
    display 'OK|' output-count
    goback.
write-account.
    unstring input-record delimited by '|'
        into account-text customer-text product-text currency-text
        status-text balance-text hold-text credit-text date-text
        sequence-text branch-text
    end-unstring
    if account-text is not numeric or date-text is not numeric
        close account-output
        display 'INPUT_ERROR|Invalid account or processing date'
        move 8 to return-code
        stop run
    end-if
    initialize AC01-RECORD
    move 078 to AC01-INSTITUTION
    compute AC01-BRANCH = function numval(branch-text)
    move account-text to AC01-ACCOUNT
    move customer-text to AC01-CUSTOMER
    move product-text to AC01-PRODUCT
    move currency-text to AC01-CURRENCY
    move status-text to AC01-STATUS
    compute AC01-BALANCE = function numval(balance-text)
    compute AC01-HOLD = function numval(hold-text)
    compute AC01-CREDIT-LINE = function numval(credit-text)
    move date-text to AC01-UPDATE-DATE
    compute AC01-SEQUENCE = function numval(sequence-text)
    write AC01-RECORD
    if output-status not = '00'
        close account-output
        display 'FILE_ERROR|WRITE failed ' output-status
        move 12 to return-code
        stop run
    end-if
    add 1 to record-count.
