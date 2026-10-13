# Spavik Python SDK

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/spavik-co/spavik-python-sdk/actions/workflows/ci.yml)

Prediction infrastructure for developers.

Add predictive capabilities to your application without building an ML stack.

## Install

Development preview: not yet published to PyPI. For now,
[install from source](CONTRIBUTING.md#install-from-source).
After the first release:

```bash
pip install spavik
```

## Quickstart

Set `SPAVIK_API_KEY` and `SPAVIK_BASE_URL` for your API environment.
Use a labeled `customers.csv` with `plan`, `seats` and `churn` columns.

```python
from spavik import Spavik

# Read your API key and API URL from the environment.
with Spavik() as client:
    # Train from past customers: "churn" is the value to predict.
    model = client.train("customers.csv", target="churn")

    # Predict churn for a new customer. This call consumes credits.
    result = model.predict({"plan": "pro", "seats": 12})
    print(result.lignes)
```

Predictions consume credits.

## What you can do

- Classification
- Regression
- Forecasting
- Dataset validation
- Model performance monitoring

## Why Spavik

Prediction used to require an ML team.
Now it’s a developer primitive.

## Documentation

[docs.spavik.co](https://docs.spavik.co)

## License

[Apache-2.0](LICENSE)
