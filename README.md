<p align="center">
  <a href="https://spavik.co">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://docs.spavik.co/logo-dark.svg">
      <img src="https://docs.spavik.co/logo-light.svg" alt="Spavik" width="180">
    </picture>
  </a>
</p>

# Spavik for Python: predictions in your app, without an ML stack

[![PyPI](https://img.shields.io/pypi/v/spavik.svg)](https://pypi.org/project/spavik/)
[![Python versions](https://img.shields.io/pypi/pyversions/spavik.svg)](https://pypi.org/project/spavik/)
[![CI](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/spavik-co/spavik-python-sdk/blob/main/LICENSE)

[Spavik](https://spavik.co) is a prediction API for developers and AI agents.
You send the history your application already keeps, such as past customers,
leads, orders or shipments, and Spavik creates a model from it in one call.
Your code then asks the questions that matter to the business: will this
customer cancel, will this lead buy, what will this house sell for, how many
orders will come in tomorrow.

There is no model to design, host or retrain by hand. This package is the
official Python client: it handles authentication, retries, safe replays and
data conversion, so a prediction is a method call.

```sh
pip install spavik
```

## A first prediction in five minutes

1. Create a free account on [spavik.co](https://spavik.co) and copy your API key
   from the dashboard. No credit card is required.
2. Export it: `export SPAVIK_API_KEY="sk-spv-api-..."`
3. Download [churn.csv](https://github.com/spavik-co/spavik-python-sdk/blob/main/examples/data/churn.csv),
   120 synthetic customers with their plan, seats, support tickets and whether
   they cancelled.
4. Run this script beside the file:

```python
from spavik import Spavik

with Spavik() as client:
    # Free: does this table say anything about churn?
    report = client.evaluate("churn.csv", target="churn")
    print(report["assessment"]["message"])

    # Free: create a model from the 120 past customers.
    model = client.train("churn.csv", target="churn")

    # One credit: will this customer cancel?
    result = model.predict({"plan": "pro", "seats": 12, "tickets_90d": 2})
    print(result.predictions)
```

Keep `model.id`: the model stays available, and later predictions reuse it
without training again.

## What you can predict

Anything your history already records the answer to. Each guide below comes
with a dataset and complete code.

| Question your app asks | Answer | Guide |
|---|---|---|
| Will this customer cancel? | yes or no, with a probability | [Churn prediction](https://spavik.co/use-cases/churn-prediction) |
| Will this lead become a customer? | yes or no, with a probability | [Lead conversion](https://spavik.co/use-cases/lead-conversion-prediction) |
| What will this property sell for? | a number | [House prices](https://spavik.co/use-cases/house-price-prediction) |
| How many hours will this parcel take? | a number | [Delivery times](https://spavik.co/use-cases/delivery-time-prediction) |
| How many orders tomorrow? | the next values of a series | [Order forecast](https://spavik.co/use-cases/order-forecast) |
| What will tomorrow's peak demand be? | the next values of a series | [Electricity demand](https://spavik.co/use-cases/electricity-demand-forecast) |

Forecasting needs no model at all: send the series and the number of steps.

```python
forecast = client.forecast("sales.csv", target="sales", horizon=7)
print(forecast.points)
```

## How a model lives

`evaluate` tells you, for free, whether the data can predict the column you
chose and how it compares with a simple guess. `train` creates the model, also
for free. `predict` scores new rows and is, with `forecast`, the only billed
step. Once the real outcome is known, `model.submit_outcomes(...)` reports it,
`model.performance()` shows how the predictions held up, and `model.refresh()`
folds the new examples into the model.

Training needs at least 100 rows, and results are usually limited below 200.
Reaching that size improves the odds without promising a good model, which is
why the evaluation comes first.

## Plans

The Free plan includes 100 predictions per calendar month, reset on the 1st at
00:00 UTC, and one active model. Training, evaluation and backtests are free on
every plan. Paid plans and their limits are on the
[pricing page](https://spavik.co/pricing).

## Works with your data and your agents

Pass a CSV path, CSV or JSON text, a dict, a list of dicts or a pandas
DataFrame (`pip install "spavik[pandas]"`). Dates, `Decimal` and missing values
are converted for you. `AsyncSpavik` offers the same methods for asyncio
applications.

If you build with an AI agent, the same operations are available as tools from
the [Spavik MCP server](https://spavik.co/mcp-integration), and a
[TypeScript SDK](https://www.npmjs.com/package/spavik) covers Node.js and edge
runtimes.

## Good to know in production

**Configuration.** The client reads `SPAVIK_API_KEY`, and `SPAVIK_BASE_URL`
when set, at the moment it is created. Without a key, every call except the
public engine catalogue (`engines()`, `engine_families()`) raises
`SpavikAuthError` locally and nothing is sent. Python 3.11 or later is required.

**Timeouts.** `Spavik(timeout=...)` replaces every operation's default (15 s
for account reads, 30 s for predictions, 60 s for forecasts, 120 s for
training). It applies to each network phase of each attempt, not to the total
duration of a call with retries.

**Retries and safe replays.** Network errors and temporary API errors are
retried with backoff. Mutations carry an idempotency key, kept across retries
and left in `exc.idempotency_key` when retries run out. After a timeout the
request may have run, so replay it with the same key rather than calling again:
`train`, `forecast`, `predict`, `submit_outcomes` and `refresh` accept
`idempotency_key=...`, and a replayed key is not billed twice. A `Retry-After`
longer than 60 seconds is not waited for: the error is raised at once.

```python
model.predict(rows, idempotency_key="order-1234-score")
```

**Strings that look like files.** A single-line string ending in `.csv`, `.tsv`,
`.txt` or `.json`, or containing a path separator, is read as a file and its
content is sent. Never hand the SDK a string that comes from your own users as
data: pass rows, or a `pathlib.Path` you built yourself.

**CSV text.** Headers must be unique and non-empty, and lose their surrounding
spaces. Malformed rows raise `SpavikDataError` with the line number before any
call. Two edge cases differ from the TypeScript SDK: integers beyond 2^53 stay
Python integers (TypeScript keeps them as text), and a quote inside an unquoted
field is accepted (TypeScript refuses the file).

**Saving results.** There is no prediction history to download later. Store the
results you need, with their `request_id`, in your own database.
`result.request_id`, `result.predictions_remaining` and `result.engine_version`
come from the response headers, and `result.data` is the body as the API sent
it.

**Outcomes and data retention.** Each outcome needs a non-empty `features`
object and `actual`. To measure quality, also send the original `prediction`,
`version` and `engine`. Zero Data Retention only stops the archiving of
`evaluate`, `backtest`, `forecast` and `predict` inputs and outputs; models,
versions and outcomes are model data and are kept on every plan.

## Documentation

- [Python guide](https://docs.spavik.co/libraries/python)
- [Quickstart](https://docs.spavik.co/start) and [API reference](https://docs.spavik.co)
- [Changelog](https://github.com/spavik-co/spavik-python-sdk/blob/main/CHANGELOG.md)
- [Report an issue](https://github.com/spavik-co/spavik-python-sdk/issues)

The API may still change before 1.0, and breaking changes are listed in the
changelog. Contributions are welcome, see
[CONTRIBUTING.md](https://github.com/spavik-co/spavik-python-sdk/blob/main/CONTRIBUTING.md).

## License

[Apache-2.0](https://github.com/spavik-co/spavik-python-sdk/blob/main/LICENSE)
