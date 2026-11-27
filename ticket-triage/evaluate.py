"""Measure how good the triage is, using tickets that a human has already labelled.

    python evaluate.py data/labels.csv

labels.csv needs three columns:  id,category,priority   (the CORRECT answers, from a human)
Run it on the same small "golden set" every week. If the numbers drop, something has drifted.
It reports accuracy, how many urgent tickets were caught, and how often the human queue was used.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from triage.config import ROOT


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    labels = {r["id"]: r for r in csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8-sig"))}
    results = {r["id"]: r for r in csv.DictReader(open(ROOT / "output" / "results.csv", newline="", encoding="utf-8"))}
    common = [i for i in labels if i in results]
    if not common:
        print("No ticket ids in common between the labels file and output/results.csv")
        return 1

    cat_ok = sum(labels[i]["category"] == results[i]["category"] for i in common)
    pri_ok = sum(labels[i]["priority"] == results[i]["priority"] for i in common)
    auto = [i for i in common if results[i]["route"] == "auto"]
    auto_cat = sum(labels[i]["category"] == results[i]["category"] for i in auto)
    auto_pri = sum(labels[i]["priority"] == results[i]["priority"] for i in auto)

    true_urgent = [i for i in common if labels[i]["priority"] == "Urgent"]
    caught = [i for i in true_urgent if results[i]["priority"] == "Urgent" or results[i]["route"] == "human_review"]
    # The costly mistake: a truly urgent ticket that was auto-handled with a LOWER priority.
    dangerous = [i for i in true_urgent if results[i]["route"] == "auto" and results[i]["priority"] != "Urgent"]

    print(f"Tickets compared:                 {len(common)}")
    print(f"Category accuracy (all):          {cat_ok / len(common):.0%}")
    print(f"Priority accuracy (all):          {pri_ok / len(common):.0%}")
    if auto:
        print(f"Category accuracy (auto only):    {auto_cat / len(auto):.0%}   <- this is what customers actually get")
        print(f"Priority accuracy (auto only):    {auto_pri / len(auto):.0%}")
    print(f"Sent to humans:                   {1 - len(auto) / len(common):.0%}")
    if true_urgent:
        print(f"Urgent tickets safely handled:    {len(caught)}/{len(true_urgent)}")
    print(f"DANGEROUS misses (urgent, auto, wrong priority): {len(dangerous)}  {dangerous}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
