       *> Input card for the evening clearing adapter; signed trailing units.
       01 MV21-RECORD.
          05 MV21-REFERENCE    PIC X(24).
          05 MV21-DEBTOR       PIC X(12).
          05 MV21-CREDITOR     PIC X(12).
          05 MV21-CURRENCY     PIC X(3).
          05 MV21-AMOUNT       PIC 9(11)V99.
          05 MV21-VALUE-DATE   PIC 9(8).
          05 MV21-NARRATIVE    PIC X(40).
