"""Run a free evaluate using synthetic CSV data or a supplied CSV file."""
import argparse
import json
import os
from pathlib import Path
from spavik import Spavik

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("csv", nargs="?", default=str(Path(__file__).parent / "data/churn.csv"))
args = parser.parse_args()
if not os.environ.get("SPAVIK_API_KEY"):
    parser.error("Set SPAVIK_API_KEY in your environment.")
with Spavik() as client:
    report = client.evaluate(args.csv, target="churn")
    print(json.dumps(report, indent=2))
