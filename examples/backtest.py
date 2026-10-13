"""Run a free backtest using synthetic CSV data or a supplied CSV file."""
import argparse
import json
import os
from pathlib import Path
from spavik import Spavik

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("csv", nargs="?", default=str(Path(__file__).parent / "data/sales.csv"))
args = parser.parse_args()
if not os.environ.get("SPAVIK_API_KEY"):
    parser.error("Set SPAVIK_API_KEY in your environment.")
with Spavik() as client:
    report = client.backtest(args.csv, target="sales", horizon=7, timestamp="date", item_id="store", point_estimate="median", quantiles=[0.1, 0.5, 0.9])
    print(json.dumps(report, indent=2))
