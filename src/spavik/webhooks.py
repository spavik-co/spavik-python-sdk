"""Verification des webhooks entrants.

Le secret de signature n'est rendu qu'une fois, a la creation du webhook. La
comparaison se fait a temps constant : une comparaison naive laisse fuir, par sa
duree, le prefixe correct d'une signature forgee.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from .errors import SpavikError

TOLERANCE_SECONDES = 300


class SpavikSignatureError(SpavikError):
    """La signature ne correspond pas, ou l'horodatage est trop ancien."""


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


def verifier(
    corps: Union[str, bytes],
    entetes: Mapping[str, str],
    secret: str,
    *,
    tolerance: int = TOLERANCE_SECONDES,
) -> Dict[str, Any]:
    """Verifie la signature et rend l'evenement decode.

    L'API envoie `Spavik-Signature: t=<secondes>,v1=<hex>` et signe
    `<t>.` suivi des octets bruts. `corps` doit etre ces octets tels que recus :
    un corps deja parse puis reserialise ne redonne pas la meme signature.
    """
    if isinstance(corps, str):
        octets = corps.encode("utf-8")
    else:
        octets = bytes(corps)

    entete = _entete(entetes, "Spavik-Signature")
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
