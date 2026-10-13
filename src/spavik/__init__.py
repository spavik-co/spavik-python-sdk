"""Client Python de l'API Spavik.

Perimetre moteur : entrainer, predire, prevoir, remonter des verites, integrer,
lister, mesurer. Authentification par cle d'usage uniquement.

    from spavik import Spavik

    spavik = Spavik()                                  # lit SPAVIK_API_KEY
    model  = spavik.train("churn.csv", target="churn") # gratuit
    print(model.predict({"plan": "pro", "seats": 12}))
"""

from __future__ import annotations

__version__ = "0.1.0"

from ._contract import API_VERSION, OPERATIONS
from .client import (
    AsyncModel,
    AsyncSpavik,
    Model,
    Prediction,
    Prevision,
    Resultat,
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
from .webhooks import SpavikSignatureError

__all__ = [
    "__version__", "API_VERSION", "OPERATIONS",
    "Spavik", "AsyncSpavik", "Model", "AsyncModel",
    "Resultat", "Prediction", "Prevision",
    "SpavikError", "SpavikDataError", "SpavikTransportError", "SpavikAuthError",
    "SpavikCreditsExhausted", "SpavikQuotaExceeded", "SpavikValidationError",
    "SpavikNotFound", "SpavikConflict", "SpavikRateLimited", "SpavikUnavailable",
    "SpavikServerError", "SpavikSignatureError",
]
