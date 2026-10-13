# Contributing

Open pull requests against `dev`. Describe the problem, the public behavior that
changes and how you verified it. Use synthetic data; never include API keys or
customer datasets. Security reports go through [SECURITY.md](SECURITY.md).

## Install from source

Requires Python 3.9 or newer. Until the first PyPI release:

```sh
python -m pip install "git+https://github.com/spavik-co/spavik-python-sdk.git@dev"
```

For local development, clone `dev` and use the checks below.

## Local checks

Run from the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,pandas]"
python scripts/generate_contract.py --check
python -m pytest -q
python -m build
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
