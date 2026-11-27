"""Central settings. Everything can be changed from the .env file - no code edits needed."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The labels the model is allowed to use. Anything else is rejected as invalid output.
CATEGORIES = [
    "Billing",            # charges, refunds, invoices, promo codes, subscriptions, payment methods
    "Account Access",     # login, password reset, 2FA, locked accounts, account changes/closure
    "Technical Issue",    # app/device bugs, sync, crashes, outages
    "Order & Shipping",   # delivery, tracking, wrong/damaged items, address changes
    "Product Question",   # how-to and pre-sales questions
    "Feedback",           # praise, suggestions, feature ideas
    "Legal & Privacy",    # legal threats, formal complaints, data/privacy requests
    "Other",              # reseller/partner enquiries, job applications, anything else
]

# Highest first. The order is used to compare priorities.
PRIORITIES = ["Urgent", "High", "Normal", "Low"]


def load_dotenv(path: Path) -> None:
    """Tiny .env reader so we do not need an extra package."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Config:
    api_key: str
    fast_model: str            # cheap model, used for every ticket
    strong_model: str          # used when the fast model is unsure or fails
    confidence_threshold: float          # below this -> human review
    urgent_confidence_threshold: float   # stricter bar for tickets labelled Urgent
    max_workers: int
    requests_per_minute: int
    max_retries: int
    timeout_seconds: int
    max_body_chars: int
    cache_path: Path

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(ROOT / ".env")
        return cls(
            api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            fast_model=os.getenv("FAST_MODEL", "gemini-3.5-flash-lite"),
            strong_model=os.getenv("STRONG_MODEL", "gemini-3.8-flash"),
            confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.75")),
            urgent_confidence_threshold=float(os.getenv("URGENT_CONFIDENCE_THRESHOLD", "0.90")),
            max_workers=int(os.getenv("MAX_WORKERS", "4")),
            requests_per_minute=int(os.getenv("REQUESTS_PER_MINUTE", "30")),
            max_retries=int(os.getenv("MAX_RETRIES", "4")),
            timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", "40")),
            max_body_chars=int(os.getenv("MAX_BODY_CHARS", "2000")),
            cache_path=ROOT / "output" / "cache.sqlite",
        )
