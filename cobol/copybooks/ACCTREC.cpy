       *> Extract layout AC01 revision 18.
       01 AC01-RECORD.
          05 AC01-INSTITUTION  PIC 9(3).
          05 AC01-BRANCH       PIC 9(4).
          05 AC01-ACCOUNT      PIC 9(10).
          05 AC01-CUSTOMER     PIC X(12).
          05 AC01-PRODUCT      PIC X(4).
          05 AC01-CURRENCY     PIC X(3).
          05 AC01-STATUS       PIC X.
          05 AC01-BALANCE      PIC S9(13) COMP-3.
          05 AC01-HOLD         PIC S9(13) COMP-3.
          05 AC01-CREDIT-LINE  PIC S9(13) COMP-3.
          05 AC01-UPDATE-DATE  PIC 9(8).
          05 AC01-SEQUENCE     PIC 9(9) COMP.
          05 FILLER           PIC X(14).
