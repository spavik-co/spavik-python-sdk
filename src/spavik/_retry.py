"""Retry policy from the public OpenAPI contract; no business decisions."""
import math
import time
from email.utils import parsedate_to_datetime

STOP = {"REQUEST_INTERRUPTED", "IDEMPOTENCY_RESPONSE_UNAVAILABLE", "IDEMPOTENCY_KEY_REUSED", "CREDITS_EXHAUSTED"}
DELAYS = {"REQUEST_IN_PROGRESS": 2, "ENGINE_BUSY": 5, "ENGINE_UNAVAILABLE": 5,
          "USAGE_ACCOUNTING_UNAVAILABLE": 5, "RATE_LIMIT_UNAVAILABLE": 5, "REQUEST_LOG_UNAVAILABLE": 5}


def retry_allowed(status, code, method, path, idempotent):
    if code in STOP:
        return False
    safe = method == "GET" or idempotent or path in {"/v1/datasets/evaluate", "/v1/forecast/backtest"}
    if not safe:
        return False
    if code == "REQUEST_IN_PROGRESS":
        return bool(idempotent)
    return status is None or status in {429, 500, 502, 503, 504}


def retry_delay(value, code, fallback):
    if value is not None:
        try:
            seconds = float(value)
        except (ValueError, TypeError):
            try:
                seconds = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                seconds = float("nan")
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    return DELAYS.get(code, fallback)
