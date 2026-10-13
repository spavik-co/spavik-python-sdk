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
from typing import Any, Dict, Mapping, Optional, Union

from .errors import SpavikError

TOLERANCE_SECONDES = 300


class SpavikSignatureError(SpavikError):
    """La signature ne correspond pas, ou l'horodatage est trop ancien."""


def _entete(entetes: Mapping[str, str], *noms: str) -> Optional[str]:
    minuscules = {k.lower(): v for k, v in entetes.items()}
    for nom in noms:
        if nom.lower() in minuscules:
            return minuscules[nom.lower()]
    return None


def verifier(
    corps: Union[str, bytes],
    entetes: Mapping[str, str],
    secret: str,
    *,
    tolerance: int = TOLERANCE_SECONDES,
) -> Dict[str, Any]:
    """Verifie la signature et rend l'evenement decode.

    `corps` doit etre les octets recus tels quels. Un corps deja parse puis
    reserialise ne redonne pas la meme signature.
    """
    if isinstance(corps, str):
        octets = corps.encode("utf-8")
    else:
        octets = bytes(corps)

    signature = _entete(entetes, "X-Spavik-Signature", "X-Signature")
    if not signature:
        raise SpavikSignatureError("no signature header on the request.")
    horodatage = _entete(entetes, "X-Spavik-Timestamp", "X-Timestamp")

    if horodatage:
        try:
            emis = int(horodatage)
        except ValueError as exc:
            raise SpavikSignatureError(f"unreadable timestamp: {horodatage!r}") from exc
        ecart = abs(int(time.time()) - emis)
        if ecart > tolerance:
            raise SpavikSignatureError(
                f"timestamp is {ecart} s old, beyond the {tolerance} s tolerance. "
                "Likely a replay."
            )
        charge = f"{emis}.".encode("utf-8") + octets
    else:
        charge = octets

    attendue = hmac.new(secret.encode("utf-8"), charge, hashlib.sha256).hexdigest()
    fournie = signature.split("=", 1)[-1].strip()

    if not hmac.compare_digest(attendue, fournie):
        raise SpavikSignatureError(
            "invalid signature. Check that the body is the raw bytes as received, "
            "not re-serialised, and that the secret is the calling webhook's."
        )

    try:
        return json.loads(octets.decode("utf-8"))
    except ValueError as exc:
        raise SpavikSignatureError("valid signature but the body is not JSON.") from exc
