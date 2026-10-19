# Changelog

## Unreleased

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
