"""Spavik clients: train, predict, forecast, report outcomes, refresh, list and measure.

Operations on a trained model live on the `Model` object, so nobody has to copy
an `mdl_...` identifier by hand.
"""

# Les variantes synchrone et asynchrone partagent tout sauf l'envoi : la
# construction des requetes et les controles locaux vivent dans `_ops`, la
# lecture des reponses dans les fonctions ci-dessous.

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import (Any, AsyncIterator, Dict, Iterator, List, Literal, Mapping, Optional,
                    Type, TypeVar, cast)

import httpx

from . import _data, _ops
from ._retry import retry_after_too_long, retry_allowed, retry_delay
from . import errors as _err
from ._http import Reponse, Requete, _Base, interpreter, tracer
from ._types import BacktestReport, EvaluationReport, Usage

Task = Literal["classification", "regression"]


# --------------------------------------------------------------------------
# Resultats
# --------------------------------------------------------------------------

@dataclass
class Result:
    """What a call returns: the API data, and what helps to make sense of it.

    `data` is the response body exactly as the API sent it. The other fields
    come from response headers:

    - `cost` is 0 for a free operation and None for a billed one: the API does
      not return the amount charged.
    - `predictions_remaining` copies the X-Spavik-Predictions-Remaining header
      (monthly allowance left plus balance), None when the API does not send it.
    - `request_id` identifies the call for support (X-Spavik-Request-Id).
    - `engine_version` is the exact engine that served the call
      (X-Spavik-Model-Version), None when the API does not send it.
    """

    data: Dict[str, Any] = field(default_factory=dict)
    cost: Optional[int] = 0
    predictions_remaining: Optional[int] = None
    request_id: Optional[str] = None
    engine_version: Optional[str] = None

    @property
    def training_calibration(self) -> Optional[Dict[str, Any]]:
        """Initial test-set diagnostic returned by the performance API."""
        return self.data.get("training_calibration")

    @property
    def engine(self) -> Optional[str]:
        """Exact serving engine, distinct from the model data version."""
        return self.engine_version or self.data.get("engine")

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Read a field of `data`, like `dict.get`."""
        return self.data.get(key, default)


@dataclass
class Prediction(Result):
    """The result of `Model.predict()`."""

    @property
    def predictions(self) -> List[Dict[str, Any]]:
        """One entry per scored row, each with its own `request_id`."""
        return self.data.get("predictions", [])

    @property
    def version(self) -> Optional[int]:
        """The model version that produced these predictions."""
        return self.data.get("version")


@dataclass
class Forecast(Result):
    """The result of `forecast()`. The API returns CSV; `points` gives rows.

    The raw CSV stays available in `.csv`, to write it to a file as is.
    """

    @property
    def csv(self) -> str:
        """The forecast as the CSV text returned by the API."""
        return self.data.get("forecast_csv") or ""

    @property
    def points(self) -> List[Dict[str, Any]]:
        """The forecast as a list of rows."""
        brut = self.csv
        if not brut.strip():
            return self.data.get("forecast") or self.data.get("predictions") or []
        return _data.normaliser(brut, quoi="forecast")

    @property
    def target(self) -> Optional[str]:
        """The column that was forecast."""
        return self.data.get("target")

    @property
    def horizon(self) -> Optional[int]:
        """How many steps ahead were forecast."""
        return self.data.get("prediction_length")

    @property
    def series(self) -> Optional[int]:
        """How many series were forecast."""
        return self.data.get("n_series")

    @property
    def backtest(self) -> Optional[Dict[str, Any]]:
        """The backtest report, present when `forecast(..., backtest=True)`."""
        return self.data.get("backtest")


R = TypeVar("R", bound=Result)


def _corps(reponse: Reponse) -> Dict[str, Any]:
    return dict(reponse.corps) if isinstance(reponse.corps, Mapping) else {}


def _resultat(reponse: Reponse, cout: Optional[int], classe: Type[R]) -> R:
    return classe(data=_corps(reponse), cost=cout,
                  predictions_remaining=reponse.predictions_remaining,
                  request_id=reponse.request_id, engine_version=reponse.engine_version)


def _page(reponse: Reponse, limit: int, offset: int):
    """Rend le lot de la page et le prochain offset, ou None quand c'est fini.

    L'API dit elle-meme s'il reste des elements (pagination.has_more) ; un lot
    plus court que la limite demandee ne prouve rien, l'API plafonnant la page.
    """
    corps = _corps(reponse)
    lot = corps.get("data") or []
    pagination = corps.get("pagination") or {}
    suivant = offset + len(lot)
    if not lot:
        return lot, None
    reste = pagination.get("has_more")
    if reste is not None:
        return lot, (suivant if reste else None)
    total = pagination.get("total")
    fini = len(lot) < limit or (total is not None and suivant >= total)
    return lot, (None if fini else suivant)


def _refresh_absorbe(exc: _err.SpavikError) -> bool:
    return exc.code == "NO_PENDING_OUTCOMES"


def _model_data(reponse: Reponse, contexte: str) -> Dict[str, Any]:
    corps = _corps(reponse)
    model = dict(corps.get("model") or corps)
    if isinstance(corps.get("version"), dict):
        model["training"] = corps["version"]
    if not model.get("id"):
        # Une reponse acceptee sans identifiant ne donne aucun modele utilisable.
        raise _err.SpavikError(
            f"{contexte}: the API response carries no model id, so no model can be returned.",
            request_id=reponse.request_id,
        )
    return model


def _rapport(reponse: Reponse) -> Dict[str, Any]:
    return _corps(reponse)


# --------------------------------------------------------------------------
# Modeles
# --------------------------------------------------------------------------

class _ModelBase:
    def __init__(self, client: Any, donnees: Mapping[str, Any]) -> None:
        self._client = client
        self._donnees = dict(donnees)

    @property
    def id(self) -> str:
        """The model identifier, `mdl_...`."""
        return self._donnees["id"]

    @property
    def name(self) -> Optional[str]:
        """The model name."""
        return self._donnees.get("name")

    @property
    def version(self) -> Optional[int]:
        """The latest model version."""
        return self._donnees.get("latest_version") or self._donnees.get("version")

    @property
    def task(self) -> Optional[str]:
        """`classification` or `regression`."""
        return self._donnees.get("task")

    @property
    def data(self) -> Dict[str, Any]:
        """The model as the API describes it."""
        return dict(self._donnees)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id} {self.name!r} version={self.version}>"

    @property
    def engine(self) -> Optional[str]:
        """The exact engine serving the model."""
        return self._donnees.get("engine")

    @property
    def engine_family(self) -> Optional[str]:
        """The engine family chosen at training."""
        return self._donnees.get("engine_family")

    @property
    def training(self) -> Optional[Dict[str, Any]]:
        """Initial training diagnostics, including calibration when available."""
        return self._donnees.get("training")

    @property
    def features(self) -> List[str]:
        """The columns `predict` expects (`feature_columns` in the API).
        Empty when the API did not record them."""
        colonnes = self._donnees.get("feature_columns")
        return list(colonnes) if isinstance(colonnes, list) else []


class Model(_ModelBase):
    """A trained model, and the operations that apply to it."""

    def predict(self, rows: Any, *, engine_version: Optional[str] = None,
                idempotency_key: Optional[str] = None) -> Prediction:
        """Predict for one or more rows with the same columns as the training data.

        Billed per row at the serving engine tariff: one prediction on the
        default engine. Pass `idempotency_key` to replay a call whose outcome
        is uncertain without being billed twice; it is reused on every retry.
        """
        plan = _ops.predict(self.id, rows, engine_version=engine_version,
                            idempotency_key=idempotency_key)
        return _resultat(self._client._envoyer(plan.requete), None, Prediction)

    def submit_outcomes(self, outcomes: Any, *, idempotency_key: Optional[str] = None) -> Result:
        """Report what actually happened. Every outcome requires `features` and `actual`. Free."""
        plan = _ops.submit_outcomes(self.id, outcomes, idempotency_key=idempotency_key)
        return _resultat(self._client._envoyer(plan.requete), 0, Result)

    def refresh(self, *, idempotency_key: Optional[str] = None) -> Optional[Result]:
        """Integrate pending outcomes and produce a new model version. Free.

        Returns None when there is nothing to integrate: that is a normal
        state, not an error to catch.
        """
        plan = _ops.refresh(self.id, idempotency_key=idempotency_key)
        try:
            return _resultat(self._client._envoyer(plan.requete), 0, Result)
        except _err.SpavikError as exc:
            if _refresh_absorbe(exc):
                return None
            raise

    def archive(self) -> None:
        """Archive the model: it stops serving and frees its place in the quota.
        Its data is kept, and `restore` brings it back. Free."""
        self._client._envoyer(_ops.archive(self.id).requete)

    def restore(self) -> "Model":
        """Bring an archived model back into service. It takes a place in the
        quota again. Returns this model, updated from the API response. Free."""
        reponse = self._client._envoyer(_ops.restore(self.id).requete)
        self._donnees = _model_data(reponse, f"restoring model {self.id}")
        return self

    def performance(self, days: int = 30) -> Result:
        """Observed performance over the last `days` days, and training calibration. Free."""
        plan = _ops.performance(self.id, days)
        return _resultat(self._client._envoyer(plan.requete), 0, Result)

    def reload(self) -> "Model":
        """Read the model again from the API."""
        self._donnees = self._client.model(self.id)._donnees
        return self


class AsyncModel(_ModelBase):
    """The same object with the same methods, asynchronous."""

    async def predict(self, rows: Any, *, engine_version: Optional[str] = None,
                      idempotency_key: Optional[str] = None) -> Prediction:
        """See Model.predict. Billed per row."""
        plan = _ops.predict(self.id, rows, engine_version=engine_version,
                            idempotency_key=idempotency_key)
        return _resultat(await self._client._envoyer(plan.requete), None, Prediction)

    async def submit_outcomes(self, outcomes: Any, *,
                              idempotency_key: Optional[str] = None) -> Result:
        """See Model.submit_outcomes. Free."""
        plan = _ops.submit_outcomes(self.id, outcomes, idempotency_key=idempotency_key)
        return _resultat(await self._client._envoyer(plan.requete), 0, Result)

    async def refresh(self, *, idempotency_key: Optional[str] = None) -> Optional[Result]:
        """See Model.refresh. Returns None when there is nothing to integrate. Free."""
        plan = _ops.refresh(self.id, idempotency_key=idempotency_key)
        try:
            return _resultat(await self._client._envoyer(plan.requete), 0, Result)
        except _err.SpavikError as exc:
            if _refresh_absorbe(exc):
                return None
            raise

    async def archive(self) -> None:
        """See Model.archive. Free, undone by restore."""
        await self._client._envoyer(_ops.archive(self.id).requete)

    async def restore(self) -> "AsyncModel":
        """See Model.restore. Returns this model, updated. Free."""
        reponse = await self._client._envoyer(_ops.restore(self.id).requete)
        self._donnees = _model_data(reponse, f"restoring model {self.id}")
        return self

    async def performance(self, days: int = 30) -> Result:
        """See Model.performance. Free."""
        plan = _ops.performance(self.id, days)
        return _resultat(await self._client._envoyer(plan.requete), 0, Result)

    async def reload(self) -> "AsyncModel":
        """Read the model again from the API."""
        frais = await self._client.model(self.id)
        self._donnees = frais._donnees
        return self


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

# Le catalogue des moteurs est public : il se lit sans cle.
_REQUETE_FAMILLES = Requete(
    methode="GET", chemin="/v1/engine-families", operation="engine_families",
    delai=15.0, contexte="engine families", publique=True,
)

_REQUETE_MOTEURS = Requete(
    methode="GET", chemin="/v1/engines", operation="engines",
    delai=15.0, contexte="available engines", publique=True,
)

# Le solde et la consommation du compte. Lecture gratuite, hors du contrat
# genere (qui ne couvre que les sept operations du moteur), comme les moteurs.
_REQUETE_USAGE = Requete(
    methode="GET", chemin="/v1/usage", operation="usage",
    delai=15.0, contexte="account usage",
)


def _liste(reponse: Reponse) -> List[Dict[str, Any]]:
    entrees = reponse.corps
    return [dict(e) for e in entrees if isinstance(e, Mapping)] if isinstance(entrees, list) else []


class Spavik(_Base):
    """Synchronous client.

    `api_key` defaults to SPAVIK_API_KEY, read when the client is created.
    Without a key, every call except the engine catalogue is refused locally
    with SpavikAuthError.

    An explicit timeout overrides every operation's network timeout, per
    attempt. Omit it or use None for operation defaults.

    >>> spavik = Spavik()                          # reads SPAVIK_API_KEY
    >>> model = spavik.train("churn.csv", target="churn")
    >>> model.predict({"plan": "pro", "seats": 12})
    """

    _modele = Model

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3,
        backoff: Optional[Any] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, backoff, user_agent)
        self._http = client or httpx.Client(timeout=timeout)
        self._http_fourni = client is not None

    def close(self) -> None:
        """Close the HTTP connection pool, unless it was supplied by the caller."""
        if not self._http_fourni:
            self._http.close()

    def __enter__(self) -> "Spavik":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _envoyer(self, requete: Requete) -> Reponse:
        self._verifier_cle(requete)
        tentative = 0
        while True:
            tentative += 1
            debut = time.monotonic()
            try:
                reponse = self._http.request(
                    requete.methode, self._url(requete.chemin),
                    headers=requete.entetes(self.cle_api, self.user_agent),
                    json=requete.corps, params=requete.parametres, timeout=self._delai(requete),
                )
            except httpx.HTTPError as exc:
                tracer(requete, None, time.monotonic() - debut, None, self.cle_api, tentative)
                if tentative < self.max_retries and retry_allowed(None, None, requete.methode, requete.chemin, bool(requete.idempotence)):
                    time.sleep(self.backoff(tentative))
                    continue
                erreur = _err.SpavikTransportError(
                    f"{requete.contexte or requete.operation}: {type(exc).__name__}: {exc}"
                )
                erreur.idempotency_key = requete.idempotence
                raise erreur from exc

            recu, erreur = interpreter(reponse.status_code, reponse.headers, reponse.text, requete)
            tracer(requete, reponse.status_code, time.monotonic() - debut,
                   _rid(recu, erreur), self.cle_api, tentative)
            if erreur is None:
                return recu or Reponse()
            erreur.idempotency_key = requete.idempotence
            if tentative < self.max_retries and retry_allowed(reponse.status_code, erreur.code, requete.methode, requete.chemin, bool(requete.idempotence)):
                attente = reponse.headers.get("Retry-After")
                # Plus d'une minute d'attente : rendre la main plutot que bloquer.
                if retry_after_too_long(attente):
                    raise erreur
                time.sleep(retry_delay(attente, erreur.code, self.backoff(tentative)))
                continue
            raise erreur

    # -- operations sans modele -------------------------------------------
    def train(
        self,
        data: Any,
        *,
        target: str,
        engine_family: Optional[str] = None,
        name: Optional[str] = None,
        auto_update: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> Model:
        """Train a model to predict the `target` column from the other columns. Free.

        `data` is a DataFrame, a list of dictionaries, CSV or JSON text, or a
        file path (see the README on how strings are read). Training needs at
        least 100 rows; fewer is refused locally and nothing is sent.

        Pass `idempotency_key` to replay a call whose outcome is uncertain
        without creating a second model; it is reused on every retry.

        Model state and outcome feedback are functional data, including under
        Zero Data Retention. No additional retention opt-in is required.
        """
        # Les controles locaux d'abord : un refus prononce ici ne doit toucher
        # ni le reseau ni le catalogue des moteurs.
        plan = _ops.train(data, target=target, engine_family=engine_family, name=name,
                          auto_update=auto_update, idempotency_key=idempotency_key)
        return self._modele(self, _model_data(self._envoyer(plan.requete), "training"))

    def forecast(
        self,
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
    ) -> Forecast:
        """Forecast the `target` column `horizon` steps ahead.

        `horizon` is a whole number, at least 1. With `item_id`, each value of
        that column is its own series, and each series needs at least
        `horizon` points. Billed by the API at horizon times the serving engine
        tariff, all series included. Pass `idempotency_key` to replay a call
        whose outcome is uncertain without being billed twice.
        """
        plan = _ops.forecast(
            data, target=target, horizon=horizon, backtest=backtest, timestamp=timestamp,
            quantiles=quantiles, item_id=item_id, point_estimate=point_estimate,
            engine_family=engine_family, engine_version=engine_version,
            include_backtest_predictions=include_backtest_predictions,
            idempotency_key=idempotency_key,
        )
        return _resultat(self._envoyer(plan.requete), plan.cout, Forecast)

    def models(self, *, limit: int = 50, status: Optional[str] = None) -> Iterator[Model]:
        """Iterate over every model of the workspace, page by page.

        `limit` is the page size, capped at 200 by the API; iteration goes on
        until the last page. Serving models by default; status="archived" for
        archived ones. Free.
        """
        taille = _ops.taille_page(limit)
        offset: Optional[int] = 0
        while offset is not None:
            plan = _ops.list_models(taille, offset, status)
            lot, offset = _page(self._envoyer(plan.requete), taille, offset)
            for entree in lot:
                yield self._modele(self, entree)

    def archive(self, model_id: str) -> None:
        """Archive a model by its id, without reading it first. See Model.archive. Free."""
        self._envoyer(_ops.archive(model_id).requete)

    def restore(self, model_id: str) -> Model:
        """Bring an archived model back into service by its id, and return it. Free.

        No prior read: reading an archived model answers MODEL_ARCHIVED, which
        would make restoring impossible.
        """
        reponse = self._envoyer(_ops.restore(model_id).requete)
        return self._modele(self, _model_data(reponse, f"restoring model {model_id}"))

    def evaluate(
        self,
        data: Any,
        *,
        target: str,
        task: Optional[Task] = None,
        max_samples: Optional[int] = None,
        explain: Optional[bool] = None,
    ) -> EvaluationReport:
        """Check whether this data can predict the `target` column, without
        creating a model and without billing anything.

        Returns the API report unchanged: `validation`, `hint`, `trial` and
        `assessment` (`status`, `metric`, `message`). The same 100-row minimum
        as training applies; the API reports it in `validation`.
        `task` forces classification or regression (inferred when omitted),
        `max_samples` requests a number of context rows (capped by the plan),
        and `explain=True` also ranks every column in
        `trial["feature_importance"]`.
        """
        plan = _ops.evaluate(data, target=target, task=task, max_samples=max_samples,
                             explain=explain)
        return cast(EvaluationReport, _rapport(self._envoyer(plan.requete)))

    def backtest(
        self,
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
    ) -> BacktestReport:
        """Check what a forecast would be worth on this series, without
        returning it and without billing anything.

        Returns the API report unchanged: `validation` (length, step,
        duplicates), `hint`, `backtest` (score against simple references, per
        window) and `assessment` (`status`, `metric`, `message`).
        """
        plan = _ops.backtest(
            data, target=target, horizon=horizon, timestamp=timestamp, item_id=item_id,
            quantiles=quantiles, point_estimate=point_estimate, engine_family=engine_family,
            engine_version=engine_version, include_backtest_predictions=include_backtest_predictions,
        )
        return cast(BacktestReport, _rapport(self._envoyer(plan.requete)))

    def model(self, model_id: str) -> Model:
        """Get an existing model by its id. Free."""
        plan = _ops.get_model(model_id)
        return self._modele(self, _model_data(self._envoyer(plan.requete), f"model {model_id} details"))

    def engine_families(self) -> List[Dict[str, Any]]:
        """Engine families and the default selected by the API. Public, free."""
        return _liste(self._envoyer(_REQUETE_FAMILLES))

    def engines(self) -> List[Dict[str, Any]]:
        """Available engines as the API describes them (id, label, status).

        The API selects defaults within the chosen family. Public, free.
        """
        return _liste(self._envoyer(_REQUETE_MOTEURS))

    def usage(self) -> Usage:
        """The account as the API sees it: plan, balance (`credit_balance`),
        low balance alert, current period and usage breakdown. Free, with no
        side effect: read it before a billed batch."""
        return cast(Usage, _rapport(self._envoyer(_REQUETE_USAGE)))


class AsyncSpavik(_Base):
    """Asynchronous client, with the same operations, configuration and
    timeout precedence as Spavik. Omit timeout or use None for operation
    defaults."""

    _modele = AsyncModel

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3,
        backoff: Optional[Any] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, backoff, user_agent)
        self._http = client or httpx.AsyncClient(timeout=timeout)
        self._http_fourni = client is not None

    async def aclose(self) -> None:
        """Close the HTTP connection pool, unless it was supplied by the caller."""
        if not self._http_fourni:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncSpavik":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _envoyer(self, requete: Requete) -> Reponse:
        self._verifier_cle(requete)
        tentative = 0
        while True:
            tentative += 1
            debut = time.monotonic()
            try:
                reponse = await self._http.request(
                    requete.methode, self._url(requete.chemin),
                    headers=requete.entetes(self.cle_api, self.user_agent),
                    json=requete.corps, params=requete.parametres, timeout=self._delai(requete),
                )
            except httpx.HTTPError as exc:
                tracer(requete, None, time.monotonic() - debut, None, self.cle_api, tentative)
                if tentative < self.max_retries and retry_allowed(None, None, requete.methode, requete.chemin, bool(requete.idempotence)):
                    await asyncio.sleep(self.backoff(tentative))
                    continue
                erreur = _err.SpavikTransportError(
                    f"{requete.contexte or requete.operation}: {type(exc).__name__}: {exc}"
                )
                erreur.idempotency_key = requete.idempotence
                raise erreur from exc

            recu, erreur = interpreter(reponse.status_code, reponse.headers, reponse.text, requete)
            tracer(requete, reponse.status_code, time.monotonic() - debut,
                   _rid(recu, erreur), self.cle_api, tentative)
            if erreur is None:
                return recu or Reponse()
            erreur.idempotency_key = requete.idempotence
            if tentative < self.max_retries and retry_allowed(reponse.status_code, erreur.code, requete.methode, requete.chemin, bool(requete.idempotence)):
                attente = reponse.headers.get("Retry-After")
                if retry_after_too_long(attente):
                    raise erreur
                await asyncio.sleep(retry_delay(attente, erreur.code, self.backoff(tentative)))
                continue
            raise erreur

    async def train(
        self,
        data: Any,
        *,
        target: str,
        engine_family: Optional[str] = None,
        name: Optional[str] = None,
        auto_update: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> AsyncModel:
        """See Spavik.train. Free, at least 100 rows."""
        # Les controles locaux d'abord, comme en synchrone.
        plan = _ops.train(data, target=target, engine_family=engine_family, name=name,
                          auto_update=auto_update, idempotency_key=idempotency_key)
        return self._modele(self, _model_data(await self._envoyer(plan.requete), "training"))

    async def forecast(
        self,
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
    ) -> Forecast:
        """See Spavik.forecast. Billed at horizon times the serving engine tariff."""
        plan = _ops.forecast(
            data, target=target, horizon=horizon, backtest=backtest, timestamp=timestamp,
            quantiles=quantiles, item_id=item_id, point_estimate=point_estimate,
            engine_family=engine_family, engine_version=engine_version,
            include_backtest_predictions=include_backtest_predictions,
            idempotency_key=idempotency_key,
        )
        return _resultat(await self._envoyer(plan.requete), plan.cout, Forecast)

    async def archive(self, model_id: str) -> None:
        """See Spavik.archive. Free."""
        await self._envoyer(_ops.archive(model_id).requete)

    async def restore(self, model_id: str) -> AsyncModel:
        """See Spavik.restore. Returns the restored model. Free."""
        reponse = await self._envoyer(_ops.restore(model_id).requete)
        return self._modele(self, _model_data(reponse, f"restoring model {model_id}"))

    async def evaluate(
        self,
        data: Any,
        *,
        target: str,
        task: Optional[Task] = None,
        max_samples: Optional[int] = None,
        explain: Optional[bool] = None,
    ) -> EvaluationReport:
        """See Spavik.evaluate. Free."""
        plan = _ops.evaluate(data, target=target, task=task, max_samples=max_samples,
                             explain=explain)
        return cast(EvaluationReport, _rapport(await self._envoyer(plan.requete)))

    async def backtest(
        self,
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
    ) -> BacktestReport:
        """See Spavik.backtest. Free."""
        plan = _ops.backtest(
            data, target=target, horizon=horizon, timestamp=timestamp, item_id=item_id,
            quantiles=quantiles, point_estimate=point_estimate, engine_family=engine_family,
            engine_version=engine_version, include_backtest_predictions=include_backtest_predictions,
        )
        return cast(BacktestReport, _rapport(await self._envoyer(plan.requete)))

    async def models(self, *, limit: int = 50, status: Optional[str] = None) -> AsyncIterator[AsyncModel]:
        """See Spavik.models. `limit` is the page size, capped at 200. Free."""
        taille = _ops.taille_page(limit)
        offset: Optional[int] = 0
        while offset is not None:
            plan = _ops.list_models(taille, offset, status)
            lot, offset = _page(await self._envoyer(plan.requete), taille, offset)
            for entree in lot:
                yield self._modele(self, entree)

    async def engine_families(self) -> List[Dict[str, Any]]:
        """Engine families and the default selected by the API. Public, free."""
        return _liste(await self._envoyer(_REQUETE_FAMILLES))

    async def engines(self) -> List[Dict[str, Any]]:
        """Available engines as the API describes them (id, label, status). Public, free."""
        return _liste(await self._envoyer(_REQUETE_MOTEURS))

    async def usage(self) -> Usage:
        """See Spavik.usage: plan, balance, period, usage breakdown. Free."""
        return cast(Usage, _rapport(await self._envoyer(_REQUETE_USAGE)))

    async def model(self, model_id: str) -> AsyncModel:
        """Get an existing model by its id. Free."""
        plan = _ops.get_model(model_id)
        return self._modele(self, _model_data(await self._envoyer(plan.requete), f"model {model_id} details"))


def _rid(recu: Optional[Reponse], erreur: Optional[_err.SpavikError]) -> Optional[str]:
    if recu is not None:
        return recu.request_id
    return erreur.request_id if erreur else None
