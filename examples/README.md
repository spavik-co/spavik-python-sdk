# Examples

Run from the repository root after installing the SDK. Set `SPAVIK_API_KEY`
securely and `SPAVIK_BASE_URL` to the desired API environment. These scripts
call the real API; they are not part of offline CI tests.

```sh
python examples/evaluate.py
python examples/backtest.py
```

Both scripts perform free evaluation operations. They neither train a persistent
model nor request paid predictions. The CSV files contain synthetic integration
data, not benchmarks. Scores from these small datasets do not establish quality
on your own data. Each script also accepts a CSV path as its first argument.
