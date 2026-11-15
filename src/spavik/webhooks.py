"""Verification of incoming webhooks.

The signing secret is shown only once, when the webhook is created. The
comparison runs in constant time: a naive comparison leaks, through its
duration, the correct prefix of a forged signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from .errors import SpavikError

TOLERANCE_SECONDS = 300


class SpavikSignatureError(SpavikError):
    """The signature does not match, the timestamp is too old, or the secret is missing."""


def _entete(entetes: Mapping[str, str], nom: str) -> Optional[str]:
    for cle, valeur in entetes.items():
        if cle.lower() == nom.lower():
            return valeur
    return None


def _lire_signature(valeur: str) -> Tuple[int, List[str]]:
    """Decoupe `t=<secondes>,v1=<hex>` ; plusieurs v1 restent possibles."""
    horodatage: Optional[int] = None
    signatures: List[str] = []
    for morceau in valeur.split(","):
        cle, _, contenu = morceau.strip().partition("=")
        if cle == "t" and contenu.isdigit():
            horodatage = int(contenu)
        elif cle == "v1" and contenu:
            signatures.append(contenu.lower())
    if horodatage is None or not signatures:
        raise SpavikSignatureError(
            "unreadable Spavik-Signature header, expected t=<unix seconds>,v1=<hex>."
        )
    return horodatage, signatures


def verify(
    body: Union[str, bytes],
    headers: Mapping[str, str],
    secret: Optional[str],
    *,
    tolerance: int = TOLERANCE_SECONDS,
) -> Dict[str, Any]:
    """Verify the signature and return the decoded event.

    The API sends `Spavik-Signature: t=<seconds>,v1=<hex>` and signs `<t>.`
    followed by the raw body. `body` must be those bytes as received: a body
    parsed then serialised again does not give the same signature.

    An empty or missing `secret` raises SpavikSignatureError: with an empty
    secret, anyone could forge an event.
    """
    # Un secret vide signerait n'importe quoi : os.environ.get(..., "") ne
    # doit jamais ouvrir la porte.
    if not secret:
        raise SpavikSignatureError("missing webhook secret")
    if isinstance(body, str):
        octets = body.encode("utf-8")
    else:
        octets = bytes(body)

    entete = _entete(headers, "Spavik-Signature")
    if not entete:
        raise SpavikSignatureError("no Spavik-Signature header on the request.")
    emis, fournies = _lire_signature(entete)

    ecart = abs(int(time.time()) - emis)
    if ecart > tolerance:
        raise SpavikSignatureError(
            f"timestamp is {ecart} s old, beyond the {tolerance} s tolerance. "
            "Likely a replay."
        )

    charge = f"{emis}.".encode("utf-8") + octets
    attendue = hmac.new(secret.encode("utf-8"), charge, hashlib.sha256).hexdigest()

    if not any(hmac.compare_digest(attendue, fournie) for fournie in fournies):
        raise SpavikSignatureError(
            "invalid signature. Check that the body is the raw bytes as received, "
            "not re-serialised, and that the secret is the calling webhook's."
        )

    try:
        return json.loads(octets.decode("utf-8"))
    except ValueError as exc:
        raise SpavikSignatureError("valid signature but the body is not JSON.") from exc
