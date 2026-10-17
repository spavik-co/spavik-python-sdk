"""Erreurs Spavik.

Une exception par famille, chacune portant le code machine, le detail rendu par
l'API, le statut HTTP et le `request_id`. Ce dernier est la seule chose
exploitable pour un support : il est emis sur chaque reponse et figure dans le
message comme dans le `repr`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from ._contract import FAMILLE_PAR_CODE

# Un code machine de l'API est en majuscules avec des soulignes. La passerelle,
# elle, rend ses propres erreurs sous une autre forme :
#   {"code": 404, "message": "The current request is not defined by this API."}
# Sans ce filtre, cette phrase deviendrait le `code` de l'exception.
_CODE_MACHINE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SpavikError(Exception):
    """Racine de toutes les erreurs de la bibliotheque."""

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
    """Refus prononce en local, avant tout appel reseau.

    Rien n'a ete envoye, rien n'a ete facture.
    """


class SpavikTransportError(SpavikError):
    """Le reseau a lache, ou la reponse n'est pas exploitable."""


class SpavikAuthError(SpavikError):
    """Cle absente, invalide, revoquee, ou insuffisante pour la route."""


class SpavikCreditsExhausted(SpavikError):
    """Le solde ne couvre pas l'appel demande."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.balance = self.payload.get("balance")
        self.required = self.payload.get("required")


class SpavikQuotaExceeded(SpavikError):
    """Une limite du plan est atteinte : nombre de modeles, taille, lignes."""


class SpavikValidationError(SpavikError):
    """L'API a refuse la requete telle qu'elle est formee."""


class SpavikNotFound(SpavikError):
    """La ressource visee n'existe pas, ou n'appartient pas a ce workspace."""


class SpavikConflict(SpavikError):
    """L'etat courant interdit l'operation : rejeu, traitement en cours, rien a integrer."""


class SpavikRateLimited(SpavikError):
    """Rate limit reached; the transport respects Retry-After."""


class SpavikUnavailable(SpavikError):
    """Une dependance manque ou dort : moteur, journal analytique, stockage."""


class SpavikServerError(SpavikError):
    """Defaut cote API."""


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
    413: SpavikQuotaExceeded,
    422: SpavikValidationError,
    429: SpavikRateLimited,
    503: SpavikUnavailable,
}


def _classe(code: Optional[str], status: Optional[int]) -> type:
    """La famille du code prime ; le statut sert de repli, y compris sur un code inconnu."""
    if code:
        famille = FAMILLE_PAR_CODE.get(code)
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
