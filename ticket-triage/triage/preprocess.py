"""Cleaning and safety checks that run BEFORE any model call (free and instant)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# A log line looks like: 2026-11-12T06:00:12Z [ERROR] ota.update: handshake failed ...
LOG_LINE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z?\s+\[(ERROR|WARN|INFO|DEBUG)\]", re.I)

# Phrases customers (or attackers) use to try to steer the AI.
INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any )?(the )?(previous|prior|above|earlier)",
    r"system (note|message|prompt|override)",
    r"the rules have changed",
    r"output priority\s*=",
    r"classify this ticket as",
    r"do not (send|route|flag) (it|this)[^.]{0,30}review",
    r"\[?(assistant|system)\s*:",
    r"you are now",
    r"new instructions",
]
INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.I)

GIBBERISH_RE = re.compile(r"\b(asdf|qwer|lorem ipsum|test test|blah blah)\b", re.I)
SIGNATURE_RE = re.compile(r"^(sent from my (phone|iphone|ipad|android)|get outlook for .*)$", re.I)
EMPTY_SUBJECTS = {"", "(no subject)", "no subject", "re:", "fwd:", "re: re:", "re: re: fwd:"}


@dataclass
class Prepared:
    subject: str
    body: str                      # cleaned (and shortened if it was huge)
    fingerprint: str               # same text -> same fingerprint (used for caching / duplicates)
    original_chars: int
    log_lines_removed: int = 0
    injection_suspected: bool = False
    insufficient_reason: str = ""  # non-empty -> do not call the model, send to a human
    notes: list = field(default_factory=list)


def _clean(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _shorten(body: str, max_chars: int):
    """Very long tickets are mostly pasted logs. Keep the human-written text, summarise the logs."""
    lines = body.split("\n")
    log_lines = [ln for ln in lines if LOG_LINE.match(ln)]
    human = "\n".join(ln for ln in lines if not LOG_LINE.match(ln)).strip()
    note = ""
    if log_lines:
        levels = {}
        for ln in log_lines:
            lvl = LOG_LINE.match(ln).group(1).upper()
            levels[lvl] = levels.get(lvl, 0) + 1
        counts = ", ".join(f"{k}={v}" for k, v in sorted(levels.items()))
        note = f"\n\n[{len(log_lines)} log lines removed for length: {counts}]"
    if len(human) > max_chars:
        human = human[:max_chars] + " ...[truncated]"
    if not log_lines and len(body) > max_chars:
        human = body[:max_chars] + " ...[truncated]"
        note = ""
    return (human + note).strip(), len(log_lines)


def prepare(subject: str, body: str, max_body_chars: int = 2000) -> Prepared:
    subject = _clean(subject)
    body = _clean(body)
    original_chars = len(body)

    # Look for manipulation in the FULL original text (the attack may be hidden deep in a long log).
    injection = bool(INJECTION_RE.search(subject) or INJECTION_RE.search(body))

    short_body, removed = (body, 0)
    if len(body) > max_body_chars:
        short_body, removed = _shorten(body, max_body_chars)

    # Is there anything meaningful to classify?
    real_subject = "" if subject.lower() in EMPTY_SUBJECTS else subject
    body_lines = [ln for ln in short_body.split("\n") if ln.strip() and not SIGNATURE_RE.match(ln.strip())]
    meaningful = (real_subject + " " + " ".join(body_lines)).split()
    insufficient = ""
    if GIBBERISH_RE.search(subject + " " + body):
        insufficient = "gibberish_or_test_message"
    elif len(set(w.lower() for w in meaningful)) < 3:
        insufficient = "too_little_information"

    key = re.sub(r"\s+", " ", (subject + "|" + body).lower())
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]

    return Prepared(
        subject=subject or "(no subject)",
        body=short_body or "(empty message)",
        fingerprint=fingerprint,
        original_chars=original_chars,
        log_lines_removed=removed,
        injection_suspected=injection,
        insufficient_reason=insufficient,
    )
