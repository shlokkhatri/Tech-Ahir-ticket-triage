"""Talks to the Gemini API over plain HTTPS (only needs the `requests` package).

Handles the things that go wrong in real life: rate limits (429), server errors (5xx),
timeouts, empty/blocked answers and malformed JSON. A tiny "circuit breaker" stops us from
hammering the API when it is clearly down.
"""
from __future__ import annotations

import json
import random
import threading
import time

import requests

from .config import CATEGORIES, PRIORITIES, Config
from .prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT, build_user_message

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class ModelError(Exception):
    """Raised when a model call fails for good (after retries)."""


class RateLimiter:
    """Spaces calls out so we never exceed N requests per minute (shared by all threads)."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(per_minute, 1)
        self.lock = threading.Lock()
        self.next_time = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            wait_for = max(0.0, self.next_time - now)
            self.next_time = max(now, self.next_time) + self.interval
        if wait_for:
            time.sleep(wait_for)


class CircuitBreaker:
    """After several failures in a row, stop calling for a short cool-down."""

    def __init__(self, threshold: int = 8, cooldown: float = 20.0):
        self.threshold, self.cooldown = threshold, cooldown
        self.failures = 0
        self.open_until = 0.0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            return time.monotonic() >= self.open_until

    def success(self) -> None:
        with self.lock:
            self.failures = 0

    def failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.monotonic() + self.cooldown
                self.failures = 0


def validate(result: dict) -> dict:
    """Make sure the model's JSON is usable. Raises ValueError if not."""
    if result.get("category") not in CATEGORIES:
        raise ValueError(f"bad category: {result.get('category')!r}")
    if result.get("priority") not in PRIORITIES:
        raise ValueError(f"bad priority: {result.get('priority')!r}")
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        raise ValueError("confidence is not a number")
    return {
        "category": result["category"],
        "priority": result["priority"],
        "confidence": max(0.0, min(1.0, confidence)),
        "language": str(result.get("language", "")),
        "manipulation_attempt": bool(result.get("manipulation_attempt", False)),
        "reason": str(result.get("reason", ""))[:300],
    }


class GeminiClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.limiter = RateLimiter(cfg.requests_per_minute)
        self.breaker = CircuitBreaker()
        self.session = requests.Session()

    def classify(self, model: str, subject: str, body: str):
        """Return (validated_result_dict, usage_dict). Raises ModelError on failure."""
        if not self.breaker.allow():
            raise ModelError("circuit open: API recently failed many times in a row")

        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": build_user_message(subject, body)}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "maxOutputTokens": 2048,
            },
        }
        headers = {"x-goog-api-key": self.cfg.api_key, "Content-Type": "application/json"}
        url = f"{BASE_URL}/{model}:generateContent"

        last_error = "unknown error"
        for attempt in range(self.cfg.max_retries + 1):
            self.limiter.wait()
            try:
                resp = self.session.post(url, headers=headers, json=payload, timeout=self.cfg.timeout_seconds)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = f"network error: {type(exc).__name__}"
                self._sleep_before_retry(attempt, None)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {resp.status_code}"
                self._sleep_before_retry(attempt, resp.headers.get("Retry-After"))
                continue
            if resp.status_code != 200:
                # 400/401/403/404 will not fix themselves by retrying (bad key, bad model name...)
                self.breaker.failure()
                raise ModelError(f"HTTP {resp.status_code}: {resp.text[:300]}")

            try:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                result = validate(json.loads(text))
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                # Empty, blocked or malformed answer. One more try is cheap; then give up.
                last_error = f"unusable model output ({exc})"
                self._sleep_before_retry(attempt, None, base=0.5)
                continue

            self.breaker.success()
            usage = data.get("usageMetadata", {})
            return result, {
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
            }

        self.breaker.failure()
        raise ModelError(f"gave up after {self.cfg.max_retries + 1} attempts: {last_error}")

    @staticmethod
    def _sleep_before_retry(attempt: int, retry_after, base: float = 1.5) -> None:
        try:
            delay = float(retry_after) if retry_after else base * (2 ** attempt)
        except ValueError:
            delay = base * (2 ** attempt)
        time.sleep(min(delay, 60) + random.uniform(0, 0.5))
