# Spavik Python SDK

**Turn your data into predictions your product can use.**

Spavik is a prediction API for classification, regression and time-series
forecasting. Evaluate your data, train a model, request predictions and measure
how they perform against real outcomes, without operating model infrastructure.

The Python SDK brings Spavik to your scripts, data pipelines and backend services.
Use synchronous or asynchronous clients, with optional pandas support.

[![CI](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

[Explore Spavik](https://spavik.co) · [Documentation](https://test-docs.spavik.co/libraries/python) · [Runnable examples](examples/README.md)

## From a dataset to a feedback loop

| What you want to do | How Spavik helps |
| --- | --- |
| Predict a category or a number | Train on a table and predict from new rows, for example churn or demand. |
| Forecast a time series | Backtest historical data, then request future values and quantiles. |
| Understand a score | Compare model metrics with baselines evaluated on the same observations. |
| Learn from what actually happened | Submit real outcomes, inspect observed performance and refresh the model. |

Your data defines the customer model. Spavik engines perform the underlying
computation. Metrics and baseline comparisons come from the API, so the SDK
returns the same evaluation report as other Spavik clients.

## Try it with a small dataset

**Development preview:** the SDK has not been published to a package registry
yet. Start from `dev` with Python 3.9+. The included datasets are synthetic and
demonstrate the integration; their scores do not establish production quality.

```sh
git clone --branch dev https://github.com/spavik-co/spavik-python-sdk.git
cd spavik-python-sdk
python -m venv .venv
source .venv/bin/activate
python -m pip install .
```

For pandas DataFrames, install `".[pandas]"`. On Windows, activate the environment
with `.venv\Scripts\Activate.ps1`. The package name is `spavik`.

Set `SPAVIK_API_KEY` securely in your environment, then select your API environment:

```sh
export SPAVIK_BASE_URL="https://test-api.spavik.co"
```

The SDK reads these environment variables and authenticates with `X-API-Key`.
It does not load `.env` files automatically. Keep API keys on your server.

Start with a **free evaluation** of the sample churn dataset:

```python
from spavik import Spavik

with Spavik() as client:
    report = client.evaluate("examples/data/churn.csv", target="churn")
    print(report.get("assessment"))
```

The `assessment` summarizes the comparison with a baseline. The full report
contains the evaluated metrics and reasons when a metric cannot be calculated.
Read [how to interpret an evaluation](https://test-docs.spavik.co/guides/evaluation)
before making decisions from a score.

## Put predictions in your application

Train a model from the dataset, then send new rows for prediction:

```python
with Spavik() as client:
    model = client.train("examples/data/churn.csv", target="churn")
    result = model.predict({"plan": "pro", "seats": 12, "tickets_90d": 3})
    print(result.lignes)
```

Training is free. Predictions consume credits according to the selected engine;
check `usage()` and the [cost guide](https://test-docs.spavik.co/costs) before
making paid calls. Keep the model ID to reuse an existing model with `model(id)`.

## Backtest before forecasting

Test your forecasting setup on historical observations before requesting future
values. This backtest is free:

```python
with Spavik() as client:
    report = client.backtest(
        "examples/data/sales.csv",
        target="sales", horizon=7, timestamp="date", item_id="store",
        point_estimate="median", quantiles=[0.1, 0.5, 0.9],
    )
    print(report.get("assessment"))
```

When calling `forecast()`, use the same history, column roles, horizon and
forecast settings. Forecasting consumes credits. See the
[SDK guide](https://test-docs.spavik.co/libraries/python) for the full workflow.

## Keep measuring after deployment

A test score is a starting point. Submit the outcomes you observe, inspect model
performance and refresh when you want to incorporate the new feedback.
The [feedback-loop guide](https://test-docs.spavik.co/guides/feedback-loop)
explains how to connect predictions to actual results.

CSV and JSON files, dictionaries and lists work out of the box. Add the pandas
extra to pass DataFrames directly. `AsyncSpavik` supports asynchronous workflows.
Catch `SpavikError` or a specific subclass to handle failures; API errors include
`code`, `status` and `request_id` when available.

## Build with us

Found a bug or missing capability? [Open an issue](https://github.com/spavik-co/spavik-python-sdk/issues).
For a security issue, follow [the private reporting process](SECURITY.md).

See [CONTRIBUTING.md](CONTRIBUTING.md) for local tests and pull requests targeting
`dev`, and [RELEASING.md](RELEASING.md) for the release process. CI tests and
builds installable archives; it does not publish packages automatically.

## License

The SDK is open source under [Apache-2.0](LICENSE). See [NOTICE](NOTICE).
The hosted Spavik service and backend remain proprietary.
