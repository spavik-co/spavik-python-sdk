"""Transport.

Le meme plan de requete sert au client synchrone et au client asynchrone :
seule la fonction qui envoie change. Trois choses s'y jouent, et elles sont
identiques dans les trois composants du depot.

1. Les reprises ne portent que sur ce qui est reprenable : 429, 5xx, et les
   pannes reseau. Jamais un 4xx, qui ne changera pas d'avis.
2. La cle d'idempotence est tiree une fois par appel logique et rejouee telle
   quelle a chaque tentative. C'est elle qui evite un second debit.
3. Une reponse non JSON leve une erreur nommee, pas une erreur de decodage.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from . import errors as _err

_LOG = logging.getLogger("spavik")

REPRISES_MAX = 3
STATUTS_REPRENABLES = frozenset({429, 500, 502, 503, 504})
# Environnement de test. A remplacer par l'URL de production avant publication :
# livrer un client dont le defaut pointe sur un banc d'essai est un piege.
BASE_URL_TEST = "https://spavik-gateway-test-bnp1bedb.ew.gateway.dev"
BASE_URL_DEFAUT = os.environ.get("SPAVIK_BASE_URL", BASE_URL_TEST)


def configurer_journalisation() -> None:
    """`SPAVIK_LOG=debug` suffit a voir passer les requetes, sans proxy."""
    niveau = os.environ.get("SPAVIK_LOG", "").strip().lower()
    if not niveau or _LOG.handlers:
        return
    _LOG.setLevel({"debug": logging.DEBUG, "info": logging.INFO}.get(niveau, logging.WARNING))
    poignee = logging.StreamHandler()
    poignee.setFormatter(logging.Formatter("spavik %(message)s"))
    _LOG.addHandler(poignee)


def masquer(cle: Optional[str]) -> str:
    if not cle:
        return "none"
    return f"{cle[:14]}...{cle[-4:]}" if len(cle) > 22 else "***"


@dataclass
class Requete:
    """Un appel logique, tel qu'il sera rejoue a l'identique en cas de reprise."""

    methode: str
    chemin: str
    operation: str
    corps: Optional[Mapping[str, Any]] = None
    parametres: Optional[Mapping[str, Any]] = None
    delai: float = 30.0
    idempotence: Optional[str] = None
    contexte: str = ""

    def entetes(self, cle_api: str) -> Dict[str, str]:
        # Les cles API passent exclusivement en X-API-Key ; Bearer est reserve aux JWT.
        e = {
            "Accept": "application/json",
            "User-Agent": _agent(),
        }
        if cle_api:
            e["X-API-Key"] = cle_api
        if self.corps is not None:
            e["Content-Type"] = "application/json"
        if self.idempotence:
            e["Idempotency-Key"] = self.idempotence
        return e


def _agent() -> str:
    from . import __version__

    return f"spavik-python/{__version__}"


def nouvelle_cle_idempotence() -> str:
    return uuid.uuid4().hex


def _request_id(entetes: Mapping[str, str]) -> Optional[str]:
    for nom in ("x-request-id", "X-Request-Id", "X-Request-ID"):
        if nom in entetes:
            return entetes[nom]
    minuscules = {k.lower(): v for k, v in entetes.items()}
    return minuscules.get("x-request-id")


# Le solde voyage aussi en en-tete : chaque prediction et chaque prevision
# rend X-Spavik-Predictions-Remaining, meme quand le corps ne porte pas le solde.
ENTETE_SOLDE = "x-spavik-predictions-remaining"


def _solde_entete(entetes: Mapping[str, str]) -> Optional[int]:
    minuscules = {k.lower(): v for k, v in entetes.items()}
    valeur = minuscules.get(ENTETE_SOLDE)
    try:
        return int(valeur) if valeur is not None and str(valeur).strip() != "" else None
    except ValueError:
        return None


def interpreter(
    statut: int,
    entetes: Mapping[str, str],
    texte: str,
    requete: Requete,
) -> Tuple[Optional[Any], Optional[_err.SpavikError]]:
    """Rend soit le corps decode, soit l'erreur a lever. Jamais les deux."""
    rid = _request_id(entetes)
    content_type = (entetes.get("content-type") or entetes.get("Content-Type") or "").lower()

    if statut == 204 or not texte.strip():
        return (None, None) if statut < 400 else (
            None, _err.depuis_reponse(statut, None, rid, contexte=requete.contexte))

    if "application/json" not in content_type:
        # Une route inconnue rend la page d'erreur par defaut du serveur, en HTML.
        return None, _err.reponse_illisible(statut, content_type, texte, rid)

    try:
        corps = json.loads(texte)
    except ValueError:
        return None, _err.reponse_illisible(statut, content_type, texte, rid)

    if statut >= 400:
        return None, _err.depuis_reponse(statut, corps, rid, contexte=requete.contexte)

    if isinstance(corps, dict):
        corps.setdefault("_request_id", rid)
        solde = _solde_entete(entetes)
        if solde is not None:
            corps.setdefault("_predictions_remaining", solde)
    return corps, None


def reprenable(statut: Optional[int], tentative: int, maximum: int = REPRISES_MAX) -> bool:
    if tentative >= maximum:
        return False
    if statut is None:  # panne reseau
        return True
    return statut in STATUTS_REPRENABLES


def attente(tentative: int) -> float:
    """Exponentielle avec bruit. L'API n'expose pas de `Retry-After` a ce jour."""
    return min(8.0, 0.5 * (2 ** (tentative - 1))) * (0.75 + random.random() * 0.5)


def tracer(requete: Requete, statut: Optional[int], duree: float, rid: Optional[str],
           cle_api: str, tentative: int) -> None:
    if not _LOG.isEnabledFor(logging.DEBUG):
        return
    _LOG.debug(
        "%s %s  idem=%s  %.2fs  %s  %s%s  cle=%s",
        requete.methode,
        requete.chemin,
        (requete.idempotence or "-")[:8],
        duree,
        statut if statut is not None else "reseau",
        rid or "-",
        f"  tentative {tentative}" if tentative > 1 else "",
        masquer(cle_api),
    )


class _Base:
    """Ce que les deux transports partagent : url, cle, garde-fous."""

    def __init__(
        self,
        cle_api: Optional[str],
        base_url: Optional[str],
        delai_defaut: float,
        max_retries: int = REPRISES_MAX,
        backoff: Any = None,
    ) -> None:
        # None lit la configuration ; une chaine vide reste explicitement vide.
        self.cle_api = (os.environ.get("SPAVIK_API_KEY") or "") if cle_api is None else cle_api
        self.base_url = (base_url or BASE_URL_DEFAUT).rstrip("/")
        self.delai_defaut = delai_defaut
        # Politique de reprise, remplacable : certains appelants veulent
        # n'en faire aucune, d'autres attendre autrement.
        self.max_retries = max_retries
        self.backoff = backoff or attente
        configurer_journalisation()

    def _url(self, chemin: str) -> str:
        return f"{self.base_url}{chemin}"
