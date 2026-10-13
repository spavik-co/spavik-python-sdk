"""Les sept operations, decrites une seule fois.

Chaque fonction fait tout ce qui ne demande pas le reseau : normaliser les
entrees, appliquer les controles locaux, calculer le cout, et batir la requete.
Les clients synchrone et asynchrone se contentent ensuite de l'envoyer. C'est ce
qui garantit qu'ils se comportent a l'identique, y compris dans leurs refus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import _data, _validate
from ._contract import OPERATIONS
from ._http import Requete, nouvelle_cle_idempotence
from .errors import SpavikDataError


@dataclass
class Plan:
    """Une requete prete a partir, et ce qu'elle coutera."""

    requete: Requete
    cout: int = 0


def _delai(nom: str) -> float:
    return float(OPERATIONS[nom]["timeout"])


def train(
    data: Any,
    *,
    target: str,
    engine: Optional[str] = None,
    name: Optional[str] = None,
    explain: Optional[bool] = None,
    auto_update: Optional[bool] = None,
) -> Plan:
    lignes = _data.normaliser(data, quoi="training data")
    _validate.entrainement(lignes, target)

    corps: Dict[str, Any] = {"target": target, "data": lignes}
    for cle, valeur in (("engine", engine), ("name", name),
                        ("explain", explain), ("auto_update", auto_update)):
        if valeur is not None:
            corps[cle] = valeur

    return Plan(Requete(
        methode="POST", chemin="/v1/models", operation="train", corps=corps,
        delai=_delai("train"), idempotence=nouvelle_cle_idempotence(),
        contexte="training",
    ), cout=0)


def forecast(
    data: Any,
    *,
    target: str,
    horizon: int,
    timestamp: Optional[str] = None,
    quantiles: Optional[List[float]] = None,
    item_id: Optional[str] = None,
    point_estimate: Optional[str] = None,
) -> Plan:
    lignes = _data.normaliser(data, quoi="series to forecast")
    _validate.previsions(lignes, target, horizon, timestamp)
    cout = _validate.cout_prevision(horizon)

    corps: Dict[str, Any] = {"target": target, "horizon": horizon, "data": lignes}
    for cle, valeur in (("timestamp", timestamp), ("quantiles", quantiles),
                        ("item_id", item_id), ("point_estimate", point_estimate)):
        if valeur is not None:
            corps[cle] = valeur

    return Plan(Requete(
        methode="POST", chemin="/v1/forecast", operation="forecast", corps=corps,
        delai=_delai("forecast"), idempotence=nouvelle_cle_idempotence(),
        contexte="forecast",
    ), cout=cout)


def predict(model_id: str, rows: Any) -> Plan:
    lignes = _data.normaliser(rows, quoi="rows to score")
    _validate.prediction(lignes)
    return Plan(Requete(
        methode="POST", chemin=f"/v1/models/{model_id}/predict", operation="predict",
        corps={"rows": lignes}, delai=_delai("predict"),
        # Le contrat ne declare pas l'en-tete sur cette route, mais l'API
        # l'honore : la poser protege d'un second debit a la reprise.
        idempotence=nouvelle_cle_idempotence(),
        contexte="prediction",
    ), cout=_validate.cout_prediction(lignes))


def submit_outcomes(model_id: str, outcomes: Any) -> Plan:
    lignes = _data.normaliser(outcomes, quoi="outcomes")
    _validate.verites(lignes)
    return Plan(Requete(
        methode="POST", chemin=f"/v1/models/{model_id}/outcomes", operation="submit_outcomes",
        corps={"outcomes": lignes}, delai=_delai("submit_outcomes"),
        idempotence=nouvelle_cle_idempotence(),
        contexte="outcome reporting",
    ), cout=0)


def refresh(model_id: str) -> Plan:
    return Plan(Requete(
        methode="POST", chemin=f"/v1/models/{model_id}/refresh", operation="refresh",
        delai=_delai("refresh"), idempotence=nouvelle_cle_idempotence(),
        contexte="outcome integration",
    ), cout=0)


def performance(model_id: str, days: int) -> Plan:
    return Plan(Requete(
        methode="GET", chemin=f"/v1/models/{model_id}/performance", operation="performance",
        parametres={"days": days}, delai=_delai("performance"),
        contexte="observed performance",
    ), cout=0)


def list_models(limit: int, offset: int, status: Optional[str] = None) -> Plan:
    parametres: Dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        parametres["status"] = status
    return Plan(Requete(
        methode="GET", chemin="/v1/models", operation="list_models",
        parametres=parametres, delai=_delai("list_models"),
        contexte="model list" if not status else f"{status} model list",
    ), cout=0)


def evaluate(data: Any, *, target: str, engine: Optional[str] = None) -> Plan:
    """Le rapport de validation de l'entrainement et un essai du moteur, sans
    rien creer ni debiter. Aucun controle local : c'est l'API qui juge, et
    elle dit quoi corriger en premier."""
    lignes = _data.normaliser(data, quoi="data to evaluate")
    corps: Dict[str, Any] = {"target": target, "data": lignes}
    if engine is not None:
        corps["engine"] = engine
    return Plan(Requete(
        methode="POST", chemin="/v1/datasets/evaluate", operation="evaluate", corps=corps,
        delai=_delai("train"), contexte="data evaluation",
    ), cout=0)


def backtest(
    data: Any,
    *,
    target: str,
    horizon: Optional[int] = None,
    timestamp: Optional[str] = None,
    item_id: Optional[str] = None,
    quantiles: Optional[List[float]] = None,
    point_estimate: Optional[str] = None,
) -> Plan:
    """Valide une serie et rejoue des fenetres de son historique, sans rendre
    de prevision et sans debiter. L'API juge, comme pour evaluate."""
    lignes = _data.normaliser(data, quoi="series to backtest")
    # Le seul controle local : l'API prend un horizon nul pour 1 sans le dire.
    if horizon is not None and horizon < 1:
        raise SpavikDataError(f"the horizon must be at least 1, got {horizon}. Nothing was sent.")
    corps: Dict[str, Any] = {"target": target, "data": lignes}
    for cle, valeur in (("horizon", horizon), ("timestamp", timestamp), ("item_id", item_id),
                        ("quantiles", quantiles), ("point_estimate", point_estimate)):
        if valeur is not None:
            corps[cle] = valeur
    return Plan(Requete(
        methode="POST", chemin="/v1/forecast/backtest", operation="backtest", corps=corps,
        delai=_delai("forecast"), contexte="series backtest",
    ), cout=0)


def predictions(model_id: str, limit: int) -> Plan:
    return Plan(Requete(
        methode="GET", chemin=f"/v1/models/{model_id}/predictions", operation="predictions",
        parametres={"limit": limit}, delai=_delai("list_models"),
        contexte=f"prediction history of {model_id}",
    ), cout=0)


def archive(model_id: str) -> Plan:
    """Archive : le modele cesse de servir et rend sa place du quota. Ses
    artefacts sont conserves, restore le remet en service. La suppression
    definitive (DELETE) n'est pas dans le perimetre de la bibliotheque."""
    return Plan(Requete(
        methode="POST", chemin=f"/v1/models/{model_id}/archive", operation="archive",
        delai=30.0, idempotence=nouvelle_cle_idempotence(),
        contexte=f"archiving model {model_id}",
    ), cout=0)


def restore(model_id: str) -> Plan:
    """Remet en service un modele archive ; il reprend une place du quota."""
    return Plan(Requete(
        methode="POST", chemin=f"/v1/models/{model_id}/restore", operation="restore",
        delai=30.0, idempotence=nouvelle_cle_idempotence(),
        contexte=f"restoring model {model_id}",
    ), cout=0)


def get_model(model_id: str) -> Plan:
    return Plan(Requete(
        methode="GET", chemin=f"/v1/models/{model_id}", operation="list_models",
        delai=_delai("list_models"), contexte=f"model {model_id} details",
    ), cout=0)
