"""Les sept operations, decrites une seule fois.

Chaque fonction fait tout ce qui ne demande pas le reseau : normaliser les
entrees, appliquer les controles locaux, et batir la requete.
Les clients synchrone et asynchrone se contentent ensuite de l'envoyer. C'est ce
qui garantit qu'ils se comportent a l'identique, y compris dans leurs refus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from . import _data, _validate
from ._contract import OPERATIONS
from ._http import Requete, nouvelle_cle_idempotence


@dataclass
class Plan:
    """Une requete prete a partir ; cout inconnu pour les operations facturees."""

    requete: Requete
    cout: Optional[int] = 0


def _delai(nom: str) -> float:
    return float(OPERATIONS[nom]["timeout"])


def _modele(model_id: str) -> str:
    """Le chemin d'un modele, identifiant encode : "../usage" ou "?status=" ne
    doivent jamais changer la route appelee."""
    return f"/v1/models/{quote(str(model_id), safe='')}"


def _cle(idempotency_key: Optional[str]) -> str:
    """La cle fournie par l'appelant prime : c'est elle qui permet de rejouer
    sans risque un appel dont l'issue est incertaine."""
    return idempotency_key or nouvelle_cle_idempotence()


# L'API plafonne une page de liste a ce nombre d'elements.
LIMITE_PAGE_MAX = 200


def train(
    data: Any,
    *,
    target: str,
    engine_family: Optional[str] = None,
    name: Optional[str] = None,
    auto_update: Optional[bool] = None,
    idempotency_key: Optional[str] = None,
) -> Plan:
    lignes = _data.normaliser(data, quoi="training data")
    _validate.entrainement(lignes, target)

    corps: Dict[str, Any] = {"target": target, "data": lignes}
    for cle, valeur in (("engine_family", engine_family), ("name", name),
                        ("auto_update", auto_update)):
        if valeur is not None:
            corps[cle] = valeur

    return Plan(Requete(
        methode="POST", chemin="/v1/models", operation="train", corps=corps,
        delai=_delai("train"), idempotence=_cle(idempotency_key),
        contexte="training",
    ), cout=0)


def forecast(
    data: Any,
    *,
    target: str,
    horizon: int,
    backtest: Optional[bool] = None,
    timestamp: Optional[str] = None,
    quantiles: Optional[List[float]] = None,
    item_id: Optional[str] = None,
    point_estimate: Optional[str] = None,
    engine_family: Optional[str] = None,
    engine_version: Optional[str] = None,
    include_backtest_predictions: Optional[bool] = None,
    idempotency_key: Optional[str] = None,
) -> Plan:
    lignes = _data.normaliser(data, quoi="series to forecast")
    _validate.previsions(lignes, target, horizon, timestamp, item_id)
    cout = None  # The API does not expose the charged amount.

    corps: Dict[str, Any] = {"target": target, "horizon": horizon, "data": lignes}
    for cle, valeur in (("timestamp", timestamp), ("quantiles", quantiles),
                        ("item_id", item_id), ("point_estimate", point_estimate),
                        ("engine_family", engine_family), ("engine_version", engine_version),
                        ("backtest", backtest), ("include_backtest_predictions", include_backtest_predictions)):
        if valeur is not None:
            corps[cle] = valeur

    return Plan(Requete(
        methode="POST", chemin="/v1/forecast", operation="forecast", corps=corps,
        delai=_delai("forecast"), idempotence=_cle(idempotency_key),
        contexte="forecast",
    ), cout=cout)


def predict(model_id: str, rows: Any, *, engine_version: Optional[str] = None,
            idempotency_key: Optional[str] = None) -> Plan:
    lignes = _data.normaliser(rows, quoi="rows to score")
    _validate.prediction(lignes)
    return Plan(Requete(
        methode="POST", chemin=f"{_modele(model_id)}/predict", operation="predict",
        corps={"rows": lignes, **({"engine_version": engine_version} if engine_version is not None else {})}, delai=_delai("predict"),
        # La meme cle et le meme corps a chaque tentative.
        idempotence=_cle(idempotency_key),
        contexte="prediction",
    ), cout=None)


def submit_outcomes(model_id: str, outcomes: Any, *,
                    idempotency_key: Optional[str] = None) -> Plan:
    lignes = _data.normaliser(outcomes, quoi="outcomes")
    _validate.verites(lignes)
    return Plan(Requete(
        methode="POST", chemin=f"{_modele(model_id)}/outcomes", operation="submit_outcomes",
        corps={"outcomes": lignes}, delai=_delai("submit_outcomes"),
        idempotence=_cle(idempotency_key),
        contexte="outcome reporting",
    ), cout=0)


def refresh(model_id: str, *, idempotency_key: Optional[str] = None) -> Plan:
    return Plan(Requete(
        methode="POST", chemin=f"{_modele(model_id)}/refresh", operation="refresh",
        delai=_delai("refresh"), idempotence=_cle(idempotency_key),
        contexte="outcome integration",
    ), cout=0)


def performance(model_id: str, days: int) -> Plan:
    return Plan(Requete(
        methode="GET", chemin=f"{_modele(model_id)}/performance", operation="performance",
        parametres={"days": days}, delai=_delai("performance"),
        contexte="observed performance",
    ), cout=0)


def taille_page(limit: int) -> int:
    return max(1, min(int(limit), LIMITE_PAGE_MAX))


def list_models(limit: int, offset: int, status: Optional[str] = None) -> Plan:
    parametres: Dict[str, Any] = {"limit": taille_page(limit), "offset": offset}
    if status:
        parametres["status"] = status
    return Plan(Requete(
        methode="GET", chemin="/v1/models", operation="list_models",
        parametres=parametres, delai=_delai("list_models"),
        contexte="model list" if not status else f"{status} model list",
    ), cout=0)


def evaluate(data: Any, *, target: str, task: Optional[str] = None,
             max_samples: Optional[int] = None, explain: Optional[bool] = None) -> Plan:
    # Le rapport de validation de l'entrainement et un essai du moteur, sans
    # rien creer ni debiter. Aucun controle local : c'est l'API qui juge, et
    # elle dit quoi corriger en premier. L'API ne lit ni engine_family ni les
    # champs de creation : seuls target, task, max_samples et explain partent.
    lignes = _data.normaliser(data, quoi="data to evaluate")
    corps: Dict[str, Any] = {"target": target, "data": lignes}
    for cle, valeur in (("task", task), ("max_samples", max_samples), ("explain", explain)):
        if valeur is not None:
            corps[cle] = valeur
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
    engine_family: Optional[str] = None,
    engine_version: Optional[str] = None,
    include_backtest_predictions: Optional[bool] = None,
) -> Plan:
    # Valide une serie et rejoue des fenetres de son historique, sans rendre
    # de prevision et sans debiter. L'API juge, comme pour evaluate.
    lignes = _data.normaliser(data, quoi="series to backtest")
    # Le seul controle local : l'API prend un horizon nul pour 1 sans le dire.
    if horizon is not None:
        _validate.horizon_entier(horizon, " Nothing was sent.")
    corps: Dict[str, Any] = {"target": target, "data": lignes}
    for cle, valeur in (("horizon", horizon), ("timestamp", timestamp), ("item_id", item_id),
                        ("quantiles", quantiles), ("point_estimate", point_estimate),
                        ("engine_family", engine_family), ("engine_version", engine_version),
                        ("include_backtest_predictions", include_backtest_predictions)):
        if valeur is not None:
            corps[cle] = valeur
    return Plan(Requete(
        methode="POST", chemin="/v1/forecast/backtest", operation="backtest", corps=corps,
        delai=_delai("forecast"), contexte="series backtest",
    ), cout=0)


def archive(model_id: str) -> Plan:
    # Archive : le modele cesse de servir et rend sa place du quota. Ses
    # artefacts sont conserves, restore le remet en service. La suppression
    # definitive (DELETE) n'est pas dans le perimetre de la bibliotheque.
    # Le contrat ne declare pas d'Idempotency-Key sur cette route.
    return Plan(Requete(
        methode="POST", chemin=f"{_modele(model_id)}/archive", operation="archive",
        delai=30.0, contexte=f"archiving model {model_id}",
    ), cout=0)


def restore(model_id: str) -> Plan:
    # Remet en service un modele archive ; il reprend une place du quota.
    return Plan(Requete(
        methode="POST", chemin=f"{_modele(model_id)}/restore", operation="restore",
        delai=30.0, contexte=f"restoring model {model_id}",
    ), cout=0)


def get_model(model_id: str) -> Plan:
    return Plan(Requete(
        methode="GET", chemin=_modele(model_id), operation="list_models",
        delai=_delai("list_models"), contexte=f"model {model_id} details",
    ), cout=0)
