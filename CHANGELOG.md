# Changelog

## Unreleased

- Breaking: the public API is in English. `Resultat` is now `Result` and
  `Prevision` is now `Forecast`. Result fields are `data`, `cost` and
  `predictions_remaining` (formerly `donnees`, `cout` and `solde`).
  `Prediction.lignes` is now `Prediction.predictions`, `Forecast.cible` is
  `Forecast.target`, `Model.donnees` is `Model.data`, and
  `spavik.webhooks.verifier(corps, entetes, secret)` is
  `verify(body, headers, secret)`, also exported from `spavik`.
- `predictions_remaining` comes only from the `X-Spavik-Predictions-Remaining`
  header, the only place the API reports it. Response bodies were searched for
  `credits_remaining`, `balance` and similar fields that the API never sends.
- Remove `SpavikCreditsExhausted.balance` and `.required`: API errors carry
  only `status`, `message` and `messageDetail`, so both were always None.
  Read `usage()` for the remaining balance.
- Debug log lines read `key=` and `attempt` instead of French labels.

- Verify webhooks against the `Spavik-Signature: t=<unix seconds>,v1=<hex>` header
  sent by the API, signing `<t>.` followed by the raw body. The timestamp is now
  required and checked against the tolerance; the former `X-Spavik-Signature`
  and `X-Spavik-Timestamp` headers are no longer read, so no real delivery could
  pass verification before this fix.

- Require non-empty `features` and `actual` for every outcome, regardless of
  data policy. `request_id` is optional correlation metadata. Inference archival
  policy does not change validation, performance or idempotent response replay.

- Remove `model.predictions()`: prediction history has been removed from the
  API for every plan. Keep prediction results and their `request_id` values
  from `predict()` in your application.

- Document inference-only Zero Data Retention and the outcome data needed for
  model refresh and performance monitoring.
- Honor explicit client timeouts in synchronous and asynchronous requests while
  preserving operation defaults when timeout is omitted or None.
- Preserve the idempotency key on exhausted network errors for uncertain outcomes.
- Parse JSON content before applying string-path heuristics; treat PathLike as
  an explicit file path and report malformed JSON as SpavikDataError.
- Reject ambiguous CSV headers, surplus fields and invalid quoting with line
  numbers instead of silently dropping values.
- Require Python 3.11 or later. Lock development dependencies and audit them in CI.
