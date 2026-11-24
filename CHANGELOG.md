# Changelog

## 0.1.3

- The API key is sent as `Authorization: Bearer <key>`, the form the API now
  documents first. `X-Spavik-Api-Key` is no longer sent, so a request carries
  a single key. Requires the API release of 2026-11-22, which accepts Bearer
  keys.
- A supplied httpx client keeps its default headers, except `Authorization`,
  which the key replaces. An `X-Spavik-Api-Key` left on it is sent as is: a
  different key makes the API answer `400 API_KEY_CONFLICT`, raised as
  `SpavikAuthError`.
- `API_KEY_CONFLICT` joins the error codes, in the authentication family.

## 0.1.2

- Documentation only: the README drops its production notes section and no
  longer describes a configurable API URL. The API lives at
  https://api.spavik.co. No code change.

## 0.1.1

- Documentation only: a new README, shown on PyPI and GitHub, that explains
  what Spavik predicts before the reference details, with links to the use
  case guides. Package metadata gains a fuller summary, keywords, topic
  classifiers and Changelog, Use cases and Pricing links. Development status
  moves to Beta. No code change.

## 0.1.0

- Breaking: training needs at least 100 rows, up from 10, as the API now
  requires. Fewer raise `SpavikDataError` ("training needs at least 100 rows,
  N provided. Nothing was sent.") before any call. The API applies the same
  minimum to `evaluate`, reported in `validation`.
- Breaking: without an API key, every call except `engines()` and
  `engine_families()` raises `SpavikAuthError` locally ("no API key: set
  SPAVIK_API_KEY or pass api_key. Nothing was sent."). `TOKEN_INVALID` is
  mapped to the authentication family.
- Breaking: `evaluate()` no longer accepts `engine_family`, which the API never
  read on this route. It accepts `task` and `max_samples` instead.
- Breaking: dictionaries returned by `evaluate()`, `backtest()` and `usage()`,
  `Result.data` and `Model.data` no longer carry the internal keys
  `_request_id`, `_predictions_remaining` and `_engine_version`. Read
  `Result.request_id`, `Result.predictions_remaining` and the new
  `Result.engine_version` instead.
- `train`, `forecast`, `evaluate` and `backtest` declare their parameters, in
  both clients, instead of `**kw`. `evaluate()`, `backtest()` and `usage()` are
  typed with the new `EvaluationReport`, `BacktestReport` and `Usage`.
- `train`, `forecast`, `Model.predict`, `Model.submit_outcomes` and
  `Model.refresh` accept `idempotency_key`, reused on every retry, to replay a
  call whose outcome is uncertain without a second charge.
- Dates, `Decimal`, `NaN`, `NaT` and infinities are converted before sending,
  for DataFrames and lists of dictionaries alike. A value that still cannot be
  sent as JSON raises `SpavikDataError` naming the column.
- `models()` follows `pagination.has_more` and caps the page size at 200: with
  `limit` above 200 it used to stop after the first page.
- `SPAVIK_BASE_URL` is read when the client is created, not when `spavik` is
  imported.
- `verify()` raises `SpavikSignatureError("missing webhook secret")` when the
  secret is empty or None, instead of accepting a signature made with an empty
  key.
- A `Retry-After` longer than 60 seconds is no longer slept through: the error
  is raised at once.
- Model identifiers are percent-encoded in URLs.
- CSV headers lose their leading and trailing spaces, as in the JavaScript SDK.
- `restore()` returns the restored model. `Model.performance()` is typed as
  returning `Result`. `Forecast.backtest` gives the backtest report of
  `forecast(..., backtest=True)`.
- A horizon that is not a whole number, such as 7.5, is refused locally. With
  `item_id`, each series must cover the horizon, and the `item_id` column must
  exist.
- `410 ENGINE_RETIRED` raises `SpavikConflict`. A training response without a
  model id raises `SpavikError` instead of `KeyError`.
- `archive` and `restore` no longer send an `Idempotency-Key`, which the
  contract does not declare for these routes.
- Public docstrings are in English. The README documents the Free plan
  (100 predictions per calendar month, reset on the 1st at 00:00 UTC), how a
  string that looks like a path is read, and the two remaining CSV differences
  with the JavaScript SDK.

## 0.1.0a2

- Breaking: `train()` no longer accepts `explain`. Feature importance moves to
  `evaluate(..., explain=True)`, which ranks every feature column in
  `trial["feature_importance"]` before any model is created. Measured at
  training, it multiplied the training time by the number of columns.
- `TOO_MANY_COLUMNS` is mapped to the quota error family. The API refuses
  tables with more feature columns than the plan allows
  (`limits.max_feature_columns`, 30 on public plans, target excluded).

## 0.1.0a1

First pre-release on PyPI.


- Keep CSV values with a leading zero, such as `007` or a postal code, as text
  instead of turning them into numbers. Only plain decimal notation becomes a
  number; `1_000`, `nan` and `inf` stay text.
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
