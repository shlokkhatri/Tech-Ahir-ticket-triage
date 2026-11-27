"""A fake model for testing WITHOUT an API key (python main.py --mock).

It is a very rough keyword guesser that returns the same JSON shape as Gemini. It also can
fail on purpose (--fail-rate) so you can watch the system send tickets to humans during an outage.
"""
from __future__ import annotations

import random
import re

from .gemini_client import ModelError

KEYWORDS = [
    ("Billing", r"charge|invoice|receipt|refund|renew|promo|discount|card|payment|billing|subscription"),
    ("Account Access", r"log ?in|password|reset|two-factor|2fa|locked|account|email address|login code"),
    ("Technical Issue", r"crash|sync|lag|slow|offline|disconnect|export|error|update|not responding|unreachable|down"),
    ("Order & Shipping", r"order|tracking|deliver|ship|arrived|damaged|wrong item|wrong product|address"),
    ("Legal & Privacy", r"legal|breach|complaint|data|privacy|gdpr"),
    ("Feedback", r"great|excellent|thanks|thank you|suggest|idea|would be nice|have you considered"),
    ("Product Question", r"how (do|can) i|is there a way|second user|automatically"),
]
URGENT = r"right now|unauthori[sz]ed|did not make|not mine|whole office|all our|all \d+|every device|smoke|overheat"
HIGH = r"twice|locked|days|legal|breach|damaged|wrong|not arrived|never arrived|crash"


class MockClient:
    def __init__(self, fail_rate: float = 0.0, seed: int = 7):
        self.fail_rate = fail_rate
        self.rng = random.Random(seed)

    def classify(self, model: str, subject: str, body: str):
        if self.rng.random() < self.fail_rate:
            raise ModelError("mock outage")
        text = f"{subject} {body}".lower()
        category, hits = "Other", 0
        for name, rx in KEYWORDS:
            n = len(re.findall(rx, text))
            if n > hits:
                category, hits = name, n
        if re.search(URGENT, text):
            priority = "Urgent"
        elif re.search(HIGH, text):
            priority = "High"
        elif category in ("Feedback", "Product Question", "Other"):
            priority = "Low"
        else:
            priority = "Normal"
        confidence = 0.55 if hits == 0 else min(0.95, 0.7 + 0.08 * hits)
        # The "strong" model is a little more sure of itself, like a real one would be.
        if "flash-lite" not in model and hits:
            confidence = min(0.97, confidence + 0.05)
        injected = bool(re.search(r"ignore (all )?previous|system note|the rules have changed", text))
        return (
            {"category": category, "priority": priority, "confidence": confidence, "language": "en",
             "manipulation_attempt": injected, "reason": "mock keyword guess"},
            {"input_tokens": 0, "output_tokens": 0},
        )
