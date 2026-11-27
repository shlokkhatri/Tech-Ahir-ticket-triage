"""Safety-net rules.

These keyword rules are NOT the classifier. They only act as a second opinion that can RAISE a
priority (never lower it). If a rule says "this looks Urgent" and the model says "Normal", the
ticket gets the higher priority and goes to a human. This protects against the costly mistake:
a wrong (too low) priority on an urgent ticket.
"""
from __future__ import annotations

import re

from .config import PRIORITIES

# (name, minimum priority, regex)
RULES = [
    ("fraud_or_unauthorised_use", "Urgent",
     r"unauthori[sz]ed|fraud|not mine|did not make|didn'?t make|someone is using my|hacked|compromised|"
     r"block (my|the) account|charges? i did not"),
    ("safety_risk", "Urgent",
     r"\bsmoke\b|\bsmoking\b|overheat|caught fire|\bon fire\b|\bburning\b|burnt|melted|sparks?\b|electric shock"),
    ("business_wide_outage", "Urgent",
     r"(whole|entire|all) (of )?(our|the) (office|company|sites?|devices|units|business)|"
     r"all \d+ of our|every device on our|business account|affecting all our"),
    ("legal_threat_or_complaint", "High",
     r"legal team|lawyer|solicitor|attorney|\bsue\b|lawsuit|breach of|court|formal complaint|trading standards"),
    ("privacy_law_request", "High",
     r"gdpr|data protection|subject access|what data .{0,40}collect|who it is shared with|in writing"),
    ("locked_out_for_days", "High",
     r"(locked|cannot log|can'?t log|unable to log|couldn'?t log|haven'?t been able to log).{0,80}"
     r"(\b\d+ days?\b|two days|three days|several days|since (monday|tuesday|wednesday|thursday|friday|last week))|"
     r"(\b\d+ days?\b|two days|three days|several days).{0,80}(locked|cannot log|can'?t log|unable to log)"),
    ("double_charge", "High", r"charged twice|double charge|billed twice|twice for my"),
]
COMPILED = [(name, level, re.compile(rx, re.I)) for name, level, rx in RULES]


def rank(priority: str) -> int:
    """Lower number = more urgent."""
    return PRIORITIES.index(priority)


def check(subject: str, body: str):
    """Return (minimum_priority or None, [names of rules that fired])."""
    text = f"{subject}\n{body}"
    floor, fired = None, []
    for name, level, rx in COMPILED:
        if rx.search(text):
            fired.append(name)
            if floor is None or rank(level) < rank(floor):
                floor = level
    return floor, fired
