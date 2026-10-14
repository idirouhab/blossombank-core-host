# Online region requests

The service accepts UTF-8 JSON objects with `Content-Type: application/json`.
Errors use `{ "error": { "code": "...", "message": "..." } }`. Validation errors
return 400; missing resources return 404; account and replay conflicts return 409.
An unavailable host executable returns 503.

## Authorisations

Create a hold with a caller-allocated reference and an expiry no more than 31
days away. Expiry must include its timezone.

```json
{
  "externalReference": "HOTEL-2081",
  "accountId": "1000000001",
  "currency": "EUR",
  "amountMinor": 15000,
  "reason": "Hotel deposit",
  "expiresAt": "2026-10-15T16:00:00Z"
}
```

The account's ledger balance is unchanged. Available funds exclude active
authorisations and liens and include any approved overdraft facility. Expired
authorisations cease reserving funds even before the expiry job runs.

Capture the full amount at `POST /v1/holds/{holdId}/capture`:

```json
{
  "externalReference": "CAPTURE-2081",
  "creditorAccount": "2000000001",
  "narrative": "Completed hotel stay"
}
```

The creditor must have the same currency. Partial capture and incremental
authorisations are not supported. A failed booking restores the original hold.
Release uses `POST /v1/holds/{holdId}/release` with `{}`.

## Corrections

`POST /v1/postings/{postingId}/reverse` accepts:

```json
{"externalReference":"REV-2081","reason":"Duplicate instruction"}
```

A reversal books opposite entries. It can fail if the previously credited
account has insufficient funds. Only one reversal is allowed per original
posting, and a reversal cannot itself be reversed. The original stays readable.

## Office controls

`POST /v1/accounts` opens a zero-balance retail account. Supply `accountId` (ten
digits), `customerId`, `currency` and `productCode` (`CA01`, `FX02` or `SV10`).

`POST /v1/accounts/{id}/restrictions` accepts `status`, `debitBlock`,
`overdraftMinor` and a required `reason`. A frozen account can receive credits;
debits are blocked. Closure requires a zero balance and no encumbrances.

`POST /v1/accounts/{id}/liens` accepts positive `amountMinor` and a unique
`authorityReference`. Release through `POST /v1/liens/{lienId}/release`.

Office aliases resolve through `GET /v1/aliases/resolve?alias=...&channel=OFFICE`.
An alias is specific to a channel and can have an expiry date.

Access to operator controls is managed outside this region. The bridge does not
provide an identity service or operator permission model.
