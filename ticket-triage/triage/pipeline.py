"""The heart of the project: triage ONE ticket and decide "auto" or "human review".

Flow for each ticket:
  1. Clean it up + safety checks (preprocess.py)            -> too empty? send to a human, no model call
  2. Ask the cheap model (cached if we have seen it before)
  3. Unsure or failed? ask the stronger model
  4. Cross-check priority with keyword safety rules (rules.py) -> rules can only RAISE priority
  5. Apply the review policy -> "auto" only if nothing looks doubtful
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import rules
from .cache import Cache
from .config import Config
from .gemini_client import ModelError
from .preprocess import prepare

PROMPT_VERSION = "v1"  # change this if you edit the prompt, so old cached answers are not reused


@dataclass
class Result:
    id: str
    received_at: str
    customer: str
    subject: str
    category: str = "Unclassified"
    priority: str = "Unassigned"
    confidence: float = 0.0
    route: str = "human_review"          # "auto" or "human_review"
    review_reasons: list = field(default_factory=list)
    model_used: str = "none"             # which model produced the final label
    reason: str = ""                     # the model's one-line explanation
    language: str = ""
    rules_fired: list = field(default_factory=list)
    from_cache: bool = False
    used_strong_model: bool = False
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    body_chars: int = 0


class Triager:
    def __init__(self, cfg: Config, client, cache: Cache):
        self.cfg, self.client, self.cache = cfg, client, cache

    # -- one model call, with caching ------------------------------------------------------
    def _ask(self, model: str, prepared, result: Result):
        key = f"{PROMPT_VERSION}|{model}|{prepared.fingerprint}"
        cached = self.cache.get(key)
        if cached:
            result.from_cache = True
            return cached
        answer, usage = self.client.classify(model, prepared.subject, prepared.body)
        result.input_tokens += usage.get("input_tokens", 0)
        result.output_tokens += usage.get("output_tokens", 0)
        self.cache.put(key, answer)
        return answer

    # -- main entry ------------------------------------------------------------------------
    def process(self, ticket: dict) -> Result:
        start = time.time()
        res = Result(
            id=ticket["id"], received_at=ticket.get("received_at", ""),
            customer=ticket.get("customer", ""), subject=ticket.get("subject", "") or "",
        )
        try:
            self._process(ticket, res)
        except Exception as exc:  # last line of defence: one bad ticket must never crash the run
            res.route = "human_review"
            res.review_reasons.append(f"unexpected_error:{type(exc).__name__}")
        res.latency_s = round(time.time() - start, 3)
        return res

    def _process(self, ticket: dict, res: Result) -> None:
        cfg = self.cfg
        p = prepare(ticket.get("subject", ""), ticket.get("body", ""), cfg.max_body_chars)
        res.body_chars = p.original_chars
        reasons = res.review_reasons

        # Step 1 - nothing to classify?
        if p.insufficient_reason:
            reasons.append(p.insufficient_reason)
            return
        if p.injection_suspected:
            reasons.append("possible_prompt_injection")

        # Step 2 - cheap model, with the strong model as a backup if it fails
        answer, model_used = None, cfg.fast_model
        try:
            answer = self._ask(cfg.fast_model, p, res)
        except ModelError as first_error:
            try:
                answer, model_used = self._ask(cfg.strong_model, p, res), cfg.strong_model
                res.used_strong_model = True
            except ModelError as second_error:
                reasons.append("model_unavailable")
                res.reason = f"model error: {first_error} | backup model: {second_error}"[:400]
                floor, fired = rules.check(p.subject, p.body)
                res.rules_fired = fired
                if floor:  # even with no model, the rules can tell a human how urgent it looks
                    res.priority = floor
                return

        # Step 3 - unsure? get a second opinion from the stronger model
        if (answer["confidence"] < cfg.confidence_threshold and model_used == cfg.fast_model
                and cfg.strong_model != cfg.fast_model):
            try:
                second = self._ask(cfg.strong_model, p, res)
                res.used_strong_model = True
                if second["priority"] != answer["priority"]:
                    reasons.append("models_disagree_on_priority")
                answer, model_used = second, cfg.strong_model
            except ModelError:
                pass  # keep the first answer; its low confidence will send it to a human anyway

        res.category, res.priority = answer["category"], answer["priority"]
        res.confidence, res.model_used = answer["confidence"], model_used
        res.reason, res.language = answer["reason"], answer["language"]

        # Step 4 - safety rules may raise the priority
        floor, fired = rules.check(p.subject, p.body)
        res.rules_fired = fired
        if floor and rules.rank(floor) < rules.rank(res.priority):
            reasons.append(f"rule_raised_priority:{res.priority}->{floor}")
            res.priority = floor

        # Step 5 - review policy: anything doubtful goes to a person
        if answer["manipulation_attempt"] and "possible_prompt_injection" not in reasons:
            reasons.append("possible_prompt_injection")
        if res.confidence < cfg.confidence_threshold:
            reasons.append("low_confidence")
        if res.priority == "Urgent" and res.confidence < cfg.urgent_confidence_threshold:
            reasons.append("urgent_needs_confirmation")

        res.route = "human_review" if reasons else "auto"
