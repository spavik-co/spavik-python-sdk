# Spavik Python SDK

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml)

Prediction infrastructure for developers.

Add predictive capabilities to your application without building an ML stack.

## Install

Requires Python 3.11 or later.

Development preview: not yet published to PyPI. Install from source:

```sh
python -m pip install "git+https://github.com/spavik-co/spavik-python-sdk.git@dev"
```

## Get your API key

Create a free account at [spavik.co](https://spavik.co) and generate your API key from the dashboard.

New accounts include **1,000 free predictions**. No credit card required.

```bash
export SPAVIK_API_KEY="sk-spv-api-..."
```

## Quickstart

Download [churn.csv](examples/data/churn.csv) and save it in your application's
working directory. It contains synthetic customer records with `plan`, `seats`,
`tickets_90d` and the known outcome `churn`. It demonstrates the API, not model quality.

Save this as `quickstart.py` beside the CSV:

```python
from spavik import Spavik

# Read your API key from SPAVIK_API_KEY.
with Spavik() as client:
    # Train on historical customers; "churn" is the value to predict. Training is free.
    model = client.train("churn.csv", target="churn")

    # Predict for a new customer using the same input columns. This consumes credits.
    result = model.predict({"plan": "pro", "seats": 12, "tickets_90d": 2})
    print(result.lignes)
```

```sh
python quickstart.py
```

`result.lignes` contains the predictions returned by the API. Reuse the trained
model for subsequent predictions; you do not need to train for every request.

## Timeouts and uncertain results

`Spavik(timeout=0.25)` and `AsyncSpavik(timeout=0.25)` apply that timeout to
every request, including retries. It overrides each operation's default.
Omit `timeout` or pass `None` to keep operation defaults, such as 15 seconds
for account usage, 120 for training and 60 for forecasting. The timeout applies
to each [HTTPX network phase](https://www.python-httpx.org/advanced/timeouts/)
of each attempt, not to the total duration of an operation
with retries and backoff.

When network retries are exhausted, `SpavikTransportError.idempotency_key`
preserves the key used for an idempotent request, and `__cause__` retains the
underlying HTTPX error. A read request has no idempotency key.
After a timeout, the server may already have executed the request. Keep the key
and request details to inspect the outcome or contact support. Do not blindly
call the mutation again: a new SDK call generates a new key and can repeat the
operation. The SDK does not expose a resume-by-key method.

## Input formats

The SDK accepts dictionaries, lists of dictionaries, DataFrames, raw CSV/JSON
text and file paths. JSON strings containing URLs or paths remain JSON content.
Use `pathlib.Path` to explicitly identify a file, including filenames that start
with `[` or `{`, or have no extension.

CSV headers must be unique and non-empty. Rows with more fields than the header
and invalid quoting raise `SpavikDataError` with the line number before any API
call. Missing values in shorter rows remain `None`; quoted commas and newlines
are preserved.

## Outcome feedback and data retention

Zero Data Retention only disables GCS/BigQuery archiving of the inputs and
outputs of `evaluate`, `backtest`, `forecast` and `predict`. API contracts and
behavior are identical for every data policy. Successful idempotent responses
remain replayable from the PostgreSQL technical cache for 24 hours. There is no prediction-history endpoint on any plan,
and no `model.predictions()` method. Save prediction results and their
`request_id` values in your application if you need them later. The API request
log contains technical metadata, not prediction values.

Model creation, context, diagnostics, versions and outcome feedback are
functional model data. They require no additional retention opt-in, including
under Zero Data Retention:

```python
from spavik import Spavik

with Spavik() as client:
    model = client.train("churn.csv", target="churn")
    model.submit_outcomes([
        {"features": {"plan": "pro", "seats": 12, "tickets_90d": 2}, "actual": 1},
    ])
    model.refresh()
```

Every outcome requires a non-empty `features` object and `actual`, on every
plan. An optional `request_id` is correlation metadata; no inference archive
is queried to recover features. Pending outcomes remain available until integration or model deletion.
Examples integrated into the model become part of its persistent context.
To measure prediction quality, also provide the original `prediction`, `version`
and exact `engine`, plus `probabilities` when available. These client-reported
measurements populate `observed` and `quality_reports`, with source
`client_reported_predictions`; inference archives are never used for performance.
The same rules apply to `Spavik` and `AsyncSpavik`.

## What you can do

- Classification and regression
- Time-series forecasting
- Dataset validation and evaluation
- Model performance monitoring and outcome feedback

## Documentation

See [docs.spavik.co](https://docs.spavik.co) for guides and the API reference.
For development and contributions, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE)
