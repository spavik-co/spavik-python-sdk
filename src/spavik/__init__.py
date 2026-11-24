"""Python client for the Spavik API.

Evaluate, train, predict, forecast, report outcomes, refresh, list and
measure. Authentication by API key only, sent as
`Authorization: Bearer <key>`.

    from spavik import Spavik

    spavik = Spavik()                                  # reads SPAVIK_API_KEY
    model  = spavik.train("churn.csv", target="churn") # free
    print(model.predict({"plan": "pro", "seats": 12}).predictions)
"""

from __future__ import annotations

__version__ = "0.1.3"

from ._contract import API_VERSION, OPERATIONS
from ._types import BacktestReport, EvaluationReport, Usage
from .client import (
    AsyncModel,
    AsyncSpavik,
    Forecast,
    Model,
    Prediction,
    Result,
    Spavik,
)
from .errors import (
    SpavikAuthError,
    SpavikConflict,
    SpavikCreditsExhausted,
    SpavikDataError,
    SpavikError,
    SpavikNotFound,
    SpavikQuotaExceeded,
    SpavikRateLimited,
    SpavikServerError,
    SpavikTransportError,
    SpavikUnavailable,
    SpavikValidationError,
)
from .webhooks import SpavikSignatureError, verify

__all__ = [
    "__version__", "API_VERSION", "OPERATIONS",
    "Spavik", "AsyncSpavik", "Model", "AsyncModel",
    "Result", "Prediction", "Forecast",
    "EvaluationReport", "BacktestReport", "Usage",
    "SpavikError", "SpavikDataError", "SpavikTransportError", "SpavikAuthError",
    "SpavikCreditsExhausted", "SpavikQuotaExceeded", "SpavikValidationError",
    "SpavikNotFound", "SpavikConflict", "SpavikRateLimited", "SpavikUnavailable",
    "SpavikServerError", "SpavikSignatureError", "verify",
]
