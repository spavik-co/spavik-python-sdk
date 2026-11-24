"""Spavik errors.

One exception per family, each carrying the machine code, the detail returned
by the API, the HTTP status and the `request_id`. The request id is what
support needs: the API sends it on every response, and it appears in the
message and in the `repr`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from ._contract import ERROR_FAMILY_BY_CODE

# Un code machine de l'API est en majuscules avec des soulignes. La passerelle,
# elle, rend ses propres erreurs sous une autre forme :
#   {"code": 404, "message": "The current request is not defined by this API."}
# Sans ce filtre, cette phrase deviendrait le `code` de l'exception.
_CODE_MACHINE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SpavikError(Exception):
    """Base class of every error raised by the library."""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        detail: Optional[str] = None,
        status: Optional[int] = None,
        request_id: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail
        self.status = status
        self.request_id = request_id
        self.payload = dict(payload or {})
        self.idempotency_key: Optional[str] = None

    def __str__(self) -> str:
        base = super().__str__()
        if self.request_id:
            return f"{base} (request_id: {self.request_id})"
        return base

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, status={self.status!r}, "
            f"request_id={self.request_id!r})"
        )


class SpavikDataError(SpavikError):
    """Refused locally, before any network call.

    Nothing was sent and nothing was billed.
    """


class SpavikTransportError(SpavikError):
    """Network failure or unreadable response. An idempotent request retains
    its idempotency_key for investigating an uncertain outcome. A new SDK call
    creates a new key and must not be used as a blind retry of a mutation."""


class SpavikAuthError(SpavikError):
    """API key missing, invalid, revoked, or not allowed on this route.

    Also raised with code API_KEY_CONFLICT when one request carries two
    different keys, one in Authorization and one in X-Spavik-Api-Key (for
    instance a default header on a supplied httpx client).

    A missing key is refused locally, before any request is sent.
    """


class SpavikCreditsExhausted(SpavikError):
    """The balance does not cover this call. `usage()` tells what is left."""


class SpavikQuotaExceeded(SpavikError):
    """A plan limit is reached: number of models, size, rows or columns."""


class SpavikValidationError(SpavikError):
    """The API refused the request as it was formed."""


class SpavikNotFound(SpavikError):
    """The resource does not exist, or does not belong to this workspace."""


class SpavikConflict(SpavikError):
    """The current state forbids the operation: replay, request in progress,
    nothing to integrate, archived model, or retired engine (HTTP 410)."""


class SpavikRateLimited(SpavikError):
    """Rate limit reached. The transport waits for Retry-After up to 60
    seconds; a longer wait is raised at once instead of blocking the call."""


class SpavikUnavailable(SpavikError):
    """A dependency is missing or asleep: engine, analytics log, storage."""


class SpavikServerError(SpavikError):
    """Failure on the API side."""


_PAR_FAMILLE = {
    "auth": SpavikAuthError,
    "credits": SpavikCreditsExhausted,
    "quota": SpavikQuotaExceeded,
    "validation": SpavikValidationError,
    "not_found": SpavikNotFound,
    "conflict": SpavikConflict,
    "rate_limit": SpavikRateLimited,
    "unavailable": SpavikUnavailable,
    "server": SpavikServerError,
    "encryption": SpavikAuthError,
    "hors_perimetre": SpavikError,
}

_PAR_STATUT = {
    400: SpavikValidationError,
    401: SpavikAuthError,
    402: SpavikCreditsExhausted,
    403: SpavikAuthError,
    404: SpavikNotFound,
    409: SpavikConflict,
    # 410 ENGINE_RETIRED : la version demandee n'existe plus, choisir une
    # version active ou omettre engine_version.
    410: SpavikConflict,
    413: SpavikQuotaExceeded,
    422: SpavikValidationError,
    429: SpavikRateLimited,
    503: SpavikUnavailable,
}


def _classe(code: Optional[str], status: Optional[int]) -> type:
    """La famille du code prime ; le statut sert de repli, y compris sur un code inconnu."""
    if code:
        famille = ERROR_FAMILY_BY_CODE.get(code)
        if famille and famille != "hors_perimetre":
            return _PAR_FAMILLE[famille]
    if status is not None:
        if status in _PAR_STATUT:
            return _PAR_STATUT[status]
        if status >= 500:
            return SpavikServerError
    return SpavikError


def depuis_reponse(
    status: int,
    corps: Any,
    request_id: Optional[str],
    *,
    contexte: str = "",
) -> SpavikError:
    """Construit l'exception correspondant a une reponse d'erreur de l'API."""
    code = detail = None
    payload: Mapping[str, Any] = {}
    if isinstance(corps, Mapping):
        payload = corps
        brut = corps.get("message")
        if isinstance(brut, str) and _CODE_MACHINE.match(brut):
            code = brut
        elif isinstance(brut, str):
            # Erreur emise en amont de l'API, la passerelle par exemple.
            detail = brut
        autre = corps.get("messageDetail")
        if isinstance(autre, str):
            detail = autre

    phrase = detail or code or f"HTTP {status}"
    if contexte:
        phrase = f"{contexte}: {phrase}"
    if code and detail:
        phrase = f"{phrase} [{code}]"

    return _classe(code, status)(
        phrase, code=code, detail=detail, status=status, request_id=request_id, payload=payload
    )


def reponse_illisible(status: int, content_type: str, texte: str, request_id: Optional[str]) -> SpavikTransportError:
    """L'API a repondu autre chose que du JSON.

    Le cas se produit sur une route inconnue, ou l'API rend la page d'erreur par
    defaut du serveur en HTML. Sans cette garde, l'appelant recevrait une erreur
    de decodage JSON au lieu d'une erreur exploitable.
    """
    extrait = " ".join(texte.split())[:120]
    return SpavikTransportError(
        f"non-JSON response from the API (HTTP {status}, content-type {content_type or 'missing'}): {extrait}",
        status=status,
        request_id=request_id,
    )


__all__ = [
    "SpavikError", "SpavikDataError", "SpavikTransportError", "SpavikAuthError",
    "SpavikCreditsExhausted", "SpavikQuotaExceeded", "SpavikValidationError",
    "SpavikNotFound", "SpavikConflict", "SpavikRateLimited", "SpavikUnavailable",
    "SpavikServerError",
]
