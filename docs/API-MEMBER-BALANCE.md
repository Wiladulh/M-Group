# Device member balance lookup API

This endpoint is a **read-only** lookup intended for ESP32 Cashier and Vending firmware. It does not authorize a payment, debit an account, or create a ledger/transaction record.

## Request

`POST /api/v1/devices/member-balance`

Headers:

- `X-M-Group-Device-Key: <device key>`

JSON body:

```json
{
  "card_uid": "04A1B2C3"
}
```

The card UID is sent in the JSON body rather than a URL path, to reduce exposure in access logs. The server authenticates the registered device using its provisioned device key and checks that its hardware identity is active and its type is allowed.

## Successful response

```json
{
  "member_id": "ID-A001",
  "member_name": "Example Member",
  "balance": 27500,
  "currency": "IDR"
}
```

The balance is computed by the server's financial ledger. The response contains only the fields needed to display the member and balance. Repeated reads of the same card by the same authenticated hardware identity are throttled for two seconds.

## Failure responses

- `401 device_auth_required`: device key missing.
- `403 invalid_device_key`, `device_not_active`, `device_not_provisioned`, or `device_type_not_allowed`: device authentication/state/type is not acceptable.
- `404 nfc_card_not_found_or_inactive`: card is unknown/revoked or its member is inactive.
- `404 member_account_not_found`: no active financial account is associated with the member.
- `429 balance_lookup_rate_limited`: the same hardware/card pair was queried again within the two-second duplicate-read cooldown.

## Firmware behavior

- Call this endpoint after the member taps an NFC card and the cashier operator chooses **Cek Saldo Member**.
- Show the member name and balance, or a concise error if the card cannot be resolved.
- Do not submit a payment, ask for a payment PIN, or change local/server balances during lookup.
- Keep the device key out of logs and UI. Use HTTPS where available.
- An NFC UID by itself is not cryptographic proof of card authenticity; balance lookup must not be treated as payment authorization.
- Vending can call this same endpoint using its registered device key; no client-supplied device identifier is required.
