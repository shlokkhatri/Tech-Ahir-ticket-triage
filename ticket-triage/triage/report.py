"""Writes the output files and builds the end-of-run report."""
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .config import PRIORITIES

FIELDS = ["id", "received_at", "customer", "subject", "category", "priority", "confidence", "route",
          "review_reasons", "model_used", "reason", "language", "rules_fired"]


def _row(r) -> dict:
    d = asdict(r)
    d["review_reasons"] = "; ".join(d["review_reasons"])
    d["rules_fired"] = "; ".join(d["rules_fired"])
    d["confidence"] = round(d["confidence"], 2)
    return {k: d[k] for k in FIELDS}


def _percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * pct))]


def _count_table(title: str, counter: Counter, total: int, order=None) -> str:
    keys = order or [k for k, _ in counter.most_common()]
    lines = [f"### {title}", "", "| Value | Tickets | Share |", "|---|---:|---:|"]
    for k in keys:
        if counter.get(k):
            lines.append(f"| {k} | {counter[k]} | {counter[k] / total:.0%} |")
    return "\n".join(lines)


def write_outputs(results: list, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = sorted(results, key=lambda r: r.id)

    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(_row(r) for r in results)

    # Human review list: most urgent first, unassigned (unknown) priorities right after Urgent/High.
    def review_sort(r):
        order = {"Urgent": 0, "High": 1, "Unassigned": 2, "Normal": 3, "Low": 4}
        return (order.get(r.priority, 5), r.received_at)

    review = sorted((r for r in results if r.route == "human_review"), key=review_sort)
    with open(out_dir / "human_review_list.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(_row(r) for r in review)

    with open(out_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2, ensure_ascii=False)

    report = build_report(results, review)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    return report


def build_report(results: list, review: list) -> str:
    n = len(results)
    auto = [r for r in results if r.route == "auto"]
    reasons = Counter()
    for r in review:
        for reason in r.review_reasons:
            reasons[reason.split(":")[0]] += 1
    latencies = [r.latency_s for r in results if not r.from_cache and r.model_used != "none"]
    cached = sum(r.from_cache for r in results)
    strong = sum(r.used_strong_model for r in results)
    failed = sum("model_unavailable" in r.review_reasons for r in results)
    errors = sum(any(x.startswith("unexpected_error") for x in r.review_reasons) for r in results)
    tokens_in = sum(r.input_tokens for r in results)
    tokens_out = sum(r.output_tokens for r in results)
    urgent_auto = [r for r in auto if r.priority == "Urgent"]
    rule_raised = sum(any(x.startswith("rule_raised_priority") for x in r.review_reasons) for r in results)

    parts = [
        "# Triage report",
        "",
        f"**{n} tickets processed.** {len(auto)} handled automatically ({len(auto) / n:.0%}), "
        f"**{len(review)} sent to the human review list** ({len(review) / n:.0%}).",
        "",
        "## How the tickets were handled",
        "",
        _count_table("Final route", Counter(r.route for r in results), n),
        "",
        _count_table("Why tickets went to a human (a ticket can have several reasons)", reasons, len(review) or 1),
        "",
        "## What the tickets were about",
        "",
        _count_table("Category (all tickets)", Counter(r.category for r in results), n),
        "",
        _count_table("Priority (all tickets)", Counter(r.priority for r in results), n,
                     order=PRIORITIES + ["Unassigned"]),
        "",
        _count_table("Priority (auto-handled only)", Counter(r.priority for r in auto), len(auto) or 1,
                     order=PRIORITIES),
        "",
        "## System health",
        "",
        f"- Answers reused from cache: {cached}",
        f"- Tickets that needed the stronger model: {strong}",
        f"- Tickets where no model answer was available (sent to human): {failed}",
        f"- Unexpected internal errors (sent to human): {errors}",
        f"- Priorities raised by safety rules: {rule_raised}",
        f"- Auto-handled tickets labelled Urgent (all had confidence >= the urgent threshold): {len(urgent_auto)}",
        f"- Model latency per ticket (seconds): average {sum(latencies) / len(latencies):.2f}, "
        f"95th percentile {_percentile(latencies, 0.95):.2f}" if latencies else "- Model latency: n/a",
        f"- Tokens used: {tokens_in:,} in / {tokens_out:,} out",
        "",
        "Full details: `results.csv`, `human_review_list.csv`, `results.json`.",
    ]
    return "\n".join(parts) + "\n"
