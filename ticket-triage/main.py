"""Run the triage service:   python main.py

Reads data/tickets.csv, triages every ticket with Gemini, writes the results into output/
and prints a report. Use `python main.py --help` for options.
"""
from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from triage.cache import Cache
from triage.config import ROOT, Config
from triage.gemini_client import GeminiClient
from triage.mock_client import MockClient
from triage.pipeline import Triager
from triage.report import write_outputs


def load_tickets(path: Path) -> list:
    with open(path, newline="", encoding="utf-8-sig") as f:
        tickets = list(csv.DictReader(f))
    for t in tickets:  # empty cells can come through as None
        for k in ("id", "received_at", "customer", "subject", "body"):
            t[k] = (t.get(k) or "").strip() if k != "body" else (t.get(k) or "")
    return tickets


def main() -> int:
    ap = argparse.ArgumentParser(description="AI support-ticket triage")
    ap.add_argument("--input", default=str(ROOT / "data" / "tickets.csv"))
    ap.add_argument("--output-dir", default=str(ROOT / "output"))
    ap.add_argument("--limit", type=int, help="only process the first N tickets (good for a quick test)")
    ap.add_argument("--mock", action="store_true", help="use a fake model, no API key needed")
    ap.add_argument("--fail-rate", type=float, default=0.0, help="with --mock: share of calls that fail on purpose")
    ap.add_argument("--no-cache", action="store_true", help="ignore saved answers and ask the model again")
    ap.add_argument("--workers", type=int, help="parallel requests (default from .env)")
    args = ap.parse_args()

    cfg = Config.from_env()
    if args.workers:
        cfg.max_workers = args.workers

    if args.mock:
        client = MockClient(fail_rate=args.fail_rate)
        cache = Cache(cfg.cache_path, enabled=False)  # never mix fake answers into the real cache
        print("MOCK MODE: using a fake model (results are only a rough demo).")
    else:
        if not cfg.api_key:
            print("No Gemini API key found.\n"
                  "  1. Copy .env.example to .env\n"
                  "  2. Put your key after GEMINI_API_KEY=\n"
                  "  (or run  python main.py --mock  to try it without a key)")
            return 1
        client = GeminiClient(cfg)
        cache = Cache(cfg.cache_path, enabled=not args.no_cache)
        print(f"Models: fast={cfg.fast_model}  strong={cfg.strong_model}")

    tickets = load_tickets(Path(args.input))
    if args.limit:
        tickets = tickets[: args.limit]
    print(f"Triaging {len(tickets)} tickets with {cfg.max_workers} workers...")

    triager = Triager(cfg, client, cache)
    results = []
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        futures = [pool.submit(triager.process, t) for t in tickets]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if i % 25 == 0 or i == len(tickets):
                print(f"  {i}/{len(tickets)} done")

    failures = [r for r in results if "model_unavailable" in r.review_reasons]
    if failures:
        print(f"\nWARNING: {len(failures)} tickets could not be classified by the model. Example error:")
        print(f"  {failures[0].reason}")
        print("  (HTTP 400/403 = check your key / model name in .env;  HTTP 429 = lower REQUESTS_PER_MINUTE)\n")

    report = write_outputs(results, Path(args.output_dir))
    print("\n" + report)
    print(f"Files written to: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
