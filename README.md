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
