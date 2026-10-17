# Contributing

Open pull requests against `dev`. Describe the problem, the public behavior that
changes and how you verified it. Use synthetic data; never include API keys or
customer datasets. Security reports go through [SECURITY.md](SECURITY.md).

## Install from source

Requires Python 3.11 or newer. Until the first PyPI release:

```sh
python -m pip install "git+https://github.com/spavik-co/spavik-python-sdk.git@dev"
```

For local development, clone `dev` and use the checks below.

## Local checks

Run from the repository root:

```sh
uv sync --locked --all-extras
source .venv/bin/activate
python scripts/generate_contract.py --check
python -m pytest -q
python -m build --no-isolation
python -m twine check dist/*
python scripts/check_package.py
```

Tests use a simulated API and require no Spavik account or live service.
Dependency installation requires access to the package registry. The package
check installs the built archive in an isolated temporary application.
Examples are separate live API calls and require an API key.

## Contract metadata

`contract/sdk.json` is the versioned input for generated constants. After updating
it, run `python scripts/generate_contract.py`. CI checks that the generated file is current.
See [contract/README.md](contract/README.md). No private repository is required.
Keep the two SDKs consistent with the API's public contract; the server computes
metrics, baselines and billing decisions.

## Conventions

Public documentation, error messages and public API documentation are in English.
Follow the existing code comment style. Write commit messages in English. Preserve
public names and signatures unless a breaking change is explicitly planned.
Add focused regression coverage for behavior changes. Follow the
[code of conduct](CODE_OF_CONDUCT.md).

See [RELEASING.md](RELEASING.md) for promotion from `dev` and package publication.

## HTTP identity

Requests authenticate with `X-Spavik-Api-Key`. `X-Spavik-Client-Name` is
`spavik-sdk-python`, and `X-Spavik-Client-Version` is the installed SDK version.
The application can customize its User-Agent with `Spavik(user_agent="my-agent/1.0")`;
this does not change the SDK identity headers. Without that option, the
User-Agent contains the SDK name and version.

## Current API contract

Model creation and evaluation select an optional engine family; the API owns
the default. Prediction selects an optional engine version within that family.
Forecast and backtest accept both. Changing engine version within a model's
family does not require retraining. Engine versions and model data versions
are distinct; the exact serving engine is available on prediction/forecast
results as `engine`. The family catalogue is a separate API resource.

```python
model = client.train(rows, target="churn", engine_family="presage")
result = model.predict(new_rows, engine_version="presage-latest")
families = client.engine_families()
report = client.backtest(history, target="sales", horizon=7,
                         engine_family="presage", include_backtest_predictions=True)
```

Historical backtest predictions are not future forecasts. To include them in
a forecast response, also enable `backtest`. Diagnostics are returned unchanged:
calibration describes probabilities on the initial test set; it does not
recalibrate them or guarantee reliability. Model `training` retains the initial
version diagnostics, including calibration. Evaluation and performance retain
their complete API reports.

`cout` is `None` in Python / `null` in TypeScript for billable calls because the
API does not return the exact debit. The SDK does not calculate it from the
training engine or assume a tariff of one. Free operations keep a cost of zero.
Forecast billing is horizon times the serving engine tariff, all series included.

HTTP correlation uses `X-Spavik-Request-Id`; each prediction row's `request_id`
is a separate identifier used to submit outcomes. Retries honor `Retry-After`
and preserve the original idempotency key and payload. `REQUEST_INTERRUPTED`
and `IDEMPOTENCY_RESPONSE_UNAVAILABLE` are raised immediately: inspect the request
log or contact support with the HTTP request ID, without creating a new key.

Data preparation makes data valid: types, missingness, duplicates, availability
at the prediction cutoff and leakage checks. Feature engineering makes signal
easier to learn: recency, trailing aggregates, calendar features and lags.
The SDK sends prepared rows; it does not create these features automatically.
Generate and reuse the same transformation code for training and prediction,
using only information available at each cutoff. Learned transformations must
be fitted on training partitions, never on the complete evaluation dataset.


## Dependency maintenance

Development requires Python 3.11 or later and uv 0.13.0. Install uv using
the [official instructions](https://docs.astral.sh/uv/getting-started/installation/).
`uv sync --locked --all-extras` creates the development environment from
`uv.lock`; run `uv pip check` and `uv run --locked --all-extras pip-audit --skip-editable`
to verify it. The SDK's public dependency ranges remain independent of the
development lockfile. To update dependencies, run `uv lock --upgrade`, review
the diff, synchronize, and run all tests and the audit before merging.
Build-backend constraints in `pyproject.toml` must be updated together with
their matching lock entries. CI audits the installed dependencies without
ignoring advisories. No automatic deployment or publication is configured.

Dependabot checks routine updates on Mondays at 08:00 Europe/Paris. Minor and
patch updates are grouped into one PR per ecosystem, with at most one open
routine PR per ecosystem. Major upgrades, including GitHub Actions, require
an explicit compatibility review and are prepared separately. Security alerts
and security updates are not filtered by this version-update policy; the CI
vulnerability audits remain enabled.
