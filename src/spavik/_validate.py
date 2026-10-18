"""Controles menes en local, avant tout appel.

La bibliotheque a les donnees en main et l'API ne les a pas encore : autant
refuser ici ce qui sera refuse la-bas, avec un message qui nomme la colonne
fautive plutot qu'un code machine, et sans depenser un aller-retour.

Chaque regle vient d'un refus reellement observe sur l'API.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional, Sequence

from ._data import Lignes, colonnes
from .errors import SpavikDataError

# L'API refuse d'apprendre en dessous de ce nombre de lignes.
MIN_LIGNES_ENTRAINEMENT = 10


def _suggestion(nom: str, connues: Sequence[str]) -> str:
    proches = difflib.get_close_matches(nom, connues, n=1, cutoff=0.6)
    if proches:
        return f" Did you mean {proches[0]!r}?"
    return ""


def _apercu(connues: Sequence[str], limite: int = 8) -> str:
    tete = ", ".join(connues[:limite])
    if len(connues) > limite:
        tete += f", ... ({len(connues)} columns)"
    return tete


def colonne_presente(lignes: Lignes, nom: str, *, role: str) -> None:
    """La colonne existe, et porte au moins une valeur."""
    connues = colonnes(lignes)
    if nom not in connues:
        raise SpavikDataError(
            f"the {role} column {nom!r} is missing from the data. "
            f"Columns found: {_apercu(connues)}.{_suggestion(nom, connues)}"
        )
    if all(ligne.get(nom) is None for ligne in lignes):
        raise SpavikDataError(
            f"the {role} column {nom!r} is present but empty across all "
            f"{len(lignes)} rows."
        )


def entrainement(lignes: Lignes, cible: str) -> None:
    if len(lignes) < MIN_LIGNES_ENTRAINEMENT:
        raise SpavikDataError(
            f"training needs at least {MIN_LIGNES_ENTRAINEMENT} rows, "
            f"{len(lignes)} provided. Nothing was sent."
        )
    colonne_presente(lignes, cible, role="target")

    manquantes = sum(1 for ligne in lignes if ligne.get(cible) is None)
    if manquantes:
        restantes = len(lignes) - manquantes
        if restantes < MIN_LIGNES_ENTRAINEMENT:
            raise SpavikDataError(
                f"{manquantes} row(s) out of {len(lignes)} have no value for the target "
                f"{cible!r}, only {restantes} would be left to learn from."
            )

    if len({ligne.get(cible) for ligne in lignes}) < 2:
        raise SpavikDataError(
            f"the target {cible!r} takes a single value across all {len(lignes)} rows: "
            "there is nothing to learn."
        )


def prediction(lignes: Lignes) -> None:
    if not lignes:
        raise SpavikDataError("no rows to score. Nothing was sent.")


def previsions(lignes: Lignes, cible: str, horizon: int, timestamp: Optional[str]) -> None:
    if horizon < 1:
        raise SpavikDataError(f"the horizon must be at least 1, got {horizon}.")
    colonne_presente(lignes, cible, role="target")
    if timestamp:
        colonne_presente(lignes, timestamp, role="timestamp")

    # Une serie plus courte que son propre horizon est le cas qui a fait echouer
    # l'exemple publie de l'API : trois points pour un horizon de quatorze.
    if len(lignes) < horizon:
        raise SpavikDataError(
            f"the series has {len(lignes)} point(s) for a horizon of {horizon}. "
            "A series shorter than its horizon yields nothing usable: "
            f"provide at least {horizon} points, preferably several times more."
        )


def verites(lignes: Lignes) -> None:
    """Chaque verite dit ce qui est arrive, et de quelle prediction elle parle.

    `actual` porte la valeur observee et `features` la ligne complete.
    `request_id` reste une correlation facultative, sans recherche d'archive.
    """
    if not lignes:
        raise SpavikDataError("no outcomes to report. Nothing was sent.")

    sans_valeur = [i for i, v in enumerate(lignes) if "actual" not in v]
    if sans_valeur:
        exemple = lignes[sans_valeur[0]]
        proche = _suggestion("actual", list(exemple))
        raise SpavikDataError(
            f"{len(sans_valeur)} outcome(s) out of {len(lignes)} have no "
            f"'actual' field, the value actually observed. Fields found on the "
            f"first: {_apercu(list(exemple))}.{proche}"
        )

    invalides = [v for v in lignes
                 if not isinstance(v.get("features"), dict) or not v["features"]]
    if invalides:
        raise SpavikDataError(
            f"{len(invalides)} outcome(s) out of {len(lignes)} require "
            "'features' as a non-empty object. 'request_id' is optional "
            "correlation metadata and cannot replace features."
        )
