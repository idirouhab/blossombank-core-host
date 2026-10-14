CREATE VIEW V_AC01 AS
SELECT account_id AS ACNUM, customer_id AS CUSTNO, currency AS CCY,
       ledger_minor AS AVBAL, product_code AS PRDCD,
       CASE status WHEN 'OPEN' THEN '0' WHEN 'FROZEN' THEN '7' ELSE '9' END AS ACSTS
FROM account_master;
CREATE VIEW V_MOV21 AS
SELECT j.sequence AS RECNO, p.external_reference AS XREF, j.account_id AS ACNUM,
       j.currency AS CCY, j.delta_minor AS TRNAMT,
       substr(replace(p.business_date,'-',''),1,8) AS VALDATE,
       p.narrative AS NARR
FROM journal j JOIN posting p USING(posting_id);
CREATE TABLE parameter_override (
    parameter_group TEXT NOT NULL,
    parameter_key TEXT NOT NULL,
    parameter_value TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    PRIMARY KEY(parameter_group,parameter_key,effective_date)
);
INSERT INTO parameter_override VALUES ('STMT','SCALE','2','2009-01-01');
INSERT INTO parameter_override VALUES ('ACTL','CURRSET','EUR,USD,GBP,JPY,KWD','2024-06-01');
