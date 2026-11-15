"""Transport.

Le meme plan de requete sert au client synchrone et au client asynchrone :
seule la fonction qui envoie change. Trois choses s'y jouent, et elles sont
identiques dans les trois composants du depot.

1. Les reprises ne portent que sur ce qui est reprenable : 429, 5xx, et les
   pannes reseau. REQUEST_IN_PROGRESS (409) is retryable with the original key.
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
# SPAVIK_BASE_URL se lit a la construction du client, comme SPAVIK_API_KEY :
# lue a l'import, une variable posee ensuite (dotenv, notebook, tests) serait
# ignoree et une cle de test partirait vers la production.
BASE_URL_DEFAUT = "https://api.spavik.co"

MESSAGE_SANS_CLE = "no API key: set SPAVIK_API_KEY or pass api_key. Nothing was sent."


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
    # Une route publique (catalogue des moteurs) se lit sans cle.
    publique: bool = False

    def entetes(self, cle_api: str, user_agent: Optional[str] = None) -> Dict[str, str]:
        from . import __version__

        # Les cles API passent exclusivement en X-Spavik-Api-Key ; Bearer est reserve aux JWT.
        e = {
            "Accept": "application/json",
            "User-Agent": user_agent or _agent(),
            "X-Spavik-Client-Name": "spavik-sdk-python",
            "X-Spavik-Client-Version": __version__,
        }
        if cle_api:
            e["X-Spavik-Api-Key"] = cle_api
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
    minuscules = {k.lower(): v for k, v in entetes.items()}
    return minuscules.get("x-spavik-request-id") or minuscules.get("x-request-id")


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


@dataclass
class Reponse:
    """Le corps tel que l'API l'a rendu, et ce que portent les en-tetes.

    Les metadonnees restent hors du corps : elles ne doivent pas apparaitre
    dans les dictionnaires rendus a l'utilisateur.
    """

    corps: Any = None
    request_id: Optional[str] = None
    engine_version: Optional[str] = None
    predictions_remaining: Optional[int] = None


def interpreter(
    statut: int,
    entetes: Mapping[str, str],
    texte: str,
    requete: Requete,
) -> Tuple[Optional[Reponse], Optional[_err.SpavikError]]:
    """Rend soit la reponse decodee, soit l'erreur a lever. Jamais les deux."""
    rid = _request_id(entetes)
    content_type = (entetes.get("content-type") or entetes.get("Content-Type") or "").lower()

    if statut == 204 or not texte.strip():
        return (Reponse(None, rid), None) if statut < 400 else (
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

    minuscules = {k.lower(): v for k, v in entetes.items()}
    return Reponse(
        corps=corps,
        request_id=rid,
        engine_version=minuscules.get("x-spavik-model-version") or None,
        predictions_remaining=_solde_entete(entetes),
    ), None


def attente(tentative: int) -> float:
    """Exponentielle avec bruit. Used only when the API supplies no retry delay."""
    return min(8.0, 0.5 * (2 ** (tentative - 1))) * (0.75 + random.random() * 0.5)


def tracer(requete: Requete, statut: Optional[int], duree: float, rid: Optional[str],
           cle_api: str, tentative: int) -> None:
    if not _LOG.isEnabledFor(logging.DEBUG):
        return
    _LOG.debug(
        "%s %s  idem=%s  %.2fs  %s  %s%s  key=%s",
        requete.methode,
        requete.chemin,
        (requete.idempotence or "-")[:8],
        duree,
        statut if statut is not None else "network",
        rid or "-",
        f"  attempt {tentative}" if tentative > 1 else "",
        masquer(cle_api),
    )


class _Base:
    """Ce que les deux transports partagent : url, cle, garde-fous."""

    def __init__(
        self,
        cle_api: Optional[str],
        base_url: Optional[str],
        delai_defaut: Optional[float],
        max_retries: int = REPRISES_MAX,
        backoff: Any = None,
        user_agent: Optional[str] = None,
    ) -> None:
        # None lit la configuration ; une chaine vide reste explicitement vide.
        self.cle_api = (os.environ.get("SPAVIK_API_KEY") or "") if cle_api is None else cle_api
        self.base_url = (base_url or os.environ.get("SPAVIK_BASE_URL") or BASE_URL_DEFAUT).rstrip("/")
        self.delai_defaut = delai_defaut
        # Politique de reprise, remplacable : certains appelants veulent
        # n'en faire aucune, d'autres attendre autrement.
        self.max_retries = max_retries
        self.backoff = backoff or attente
        self.user_agent = user_agent
        configurer_journalisation()

    def _verifier_cle(self, requete: Requete) -> None:
        """Sans cle, seule une route publique part ; le reste est refuse ici."""
        if not self.cle_api and not requete.publique:
            raise _err.SpavikAuthError(MESSAGE_SANS_CLE)

    def _url(self, chemin: str) -> str:
        return f"{self.base_url}{chemin}"

    def _delai(self, requete: Requete) -> float:
        """Un delai explicite prime ; sinon conserver celui de l'operation."""
        return requete.delai if self.delai_defaut is None else self.delai_defaut
