"""Entrees polymorphes.

Le format des donnees est le sujet de l'utilisateur, pas celui de la
bibliotheque : un DataFrame, un chemin de fichier, une liste de dictionnaires ou
du CSV brut arrivent tous ici et repartent en liste de dictionnaires.
"""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Dict, Iterable, List, Sequence

from .errors import SpavikDataError

Lignes = List[Dict[str, Any]]

_EXTENSIONS_CSV = (".csv", ".tsv", ".txt")


def _depuis_csv(texte: str, origine: str) -> Lignes:
    echantillon = texte[:4096]
    try:
        dialecte = csv.Sniffer().sniff(echantillon, delimiters=",;\t|")
    except csv.Error:
        dialecte = csv.excel
    lecteur = csv.DictReader(io.StringIO(texte), dialect=dialecte)
    if not lecteur.fieldnames:
        raise SpavikDataError(f"{origine}: no readable header row.")
    lignes = [{k: _typer(v) for k, v in ligne.items() if k is not None} for ligne in lecteur]
    if not lignes:
        raise SpavikDataError(f"{origine}: header present, but no data rows.")
    return lignes


def _typer(valeur: Any) -> Any:
    """Un CSV ne porte que du texte. Les nombres redeviennent des nombres."""
    if not isinstance(valeur, str):
        return valeur
    brut = valeur.strip()
    if brut == "":
        return None
    try:
        return int(brut)
    except ValueError:
        pass
    try:
        return float(brut)
    except ValueError:
        return valeur


def _depuis_dataframe(df: Any) -> Lignes:
    lignes = df.to_dict(orient="records")
    # NaN ne survit pas a JSON : il devient null, ce que l'API sait lire.
    propre: Lignes = []
    for ligne in lignes:
        propre.append({k: (None if _est_nan(v) else _scalaire(v)) for k, v in ligne.items()})
    return propre


def _est_nan(v: Any) -> bool:
    return isinstance(v, float) and v != v


def _scalaire(v: Any) -> Any:
    """numpy.int64 et consorts ne se serialisent pas : les ramener en types Python."""
    item = getattr(v, "item", None)
    if callable(item) and type(v).__module__.startswith("numpy"):
        return item()
    return v


def normaliser(source: Any, *, quoi: str = "data") -> Lignes:
    """Ramene n'importe quelle forme acceptee a une liste de dictionnaires."""
    if source is None:
        raise SpavikDataError(f"{quoi}: nothing to send.")

    if hasattr(source, "to_dict") and hasattr(source, "columns"):
        return _depuis_dataframe(source)

    if isinstance(source, (str, os.PathLike)):
        chemin = os.fspath(source)
        # Une chaine est un chemin si elle en a l'air, sinon on la lit comme du contenu.
        ressemble = (
            len(chemin) < 4096
            and "\n" not in chemin
            and (chemin.lower().endswith(_EXTENSIONS_CSV) or chemin.lower().endswith(".json")
                 or os.path.sep in chemin)
        )
        if ressemble:
            if not os.path.exists(chemin):
                raise SpavikDataError(f"{quoi}: file not found, {chemin}")
            with open(chemin, "r", encoding="utf-8-sig", newline="") as f:
                contenu = f.read()
            if chemin.lower().endswith(".json"):
                return normaliser(json.loads(contenu), quoi=quoi)
            return _depuis_csv(contenu, chemin)
        if chemin.lstrip().startswith(("[", "{")):
            return normaliser(json.loads(chemin), quoi=quoi)
        return _depuis_csv(chemin, quoi)

    if isinstance(source, dict):
        return [dict(source)]

    if isinstance(source, Sequence) or isinstance(source, Iterable):
        lignes = list(source)
        if not lignes:
            raise SpavikDataError(f"{quoi}: the list is empty.")
        if all(isinstance(l, dict) for l in lignes):
            return [dict(l) for l in lignes]
        raise SpavikDataError(
            f"{quoi}: a list must contain dictionaries, "
            f"found {type(lignes[0]).__name__}."
        )

    raise SpavikDataError(
        f"{quoi}: unsupported type, {type(source).__name__}. "
        "Accepted forms: DataFrame, file path, list of dictionaries, CSV."
    )


def colonnes(lignes: Lignes) -> List[str]:
    """Union ordonnee des colonnes rencontrees."""
    vues: Dict[str, None] = {}
    for ligne in lignes:
        for cle in ligne:
            vues.setdefault(cle, None)
    return list(vues)
