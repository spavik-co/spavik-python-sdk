"""Client Spavik : les sept operations du perimetre moteur.

Quatre d'entre elles portent un identifiant de modele. Ces quatre-la vivent sur
l'objet `Model`, pour que personne n'ait a recopier un `mdl_...` a la main.

Les variantes synchrone et asynchrone partagent tout sauf l'envoi : la
construction des requetes et les controles locaux vivent dans `_ops`, la lecture
des reponses dans les fonctions ci-dessous.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Mapping, Optional

import httpx

from . import _data, _ops
from ._retry import retry_allowed, retry_delay
from . import errors as _err
from ._http import Requete, _Base, interpreter, tracer


# --------------------------------------------------------------------------
# Resultats
# --------------------------------------------------------------------------

@dataclass
class Result:
    """Ce que rend un appel : les donnees brutes, et ce qui aide a s'y retrouver.

    `cost` vaut 0 pour une operation gratuite et None pour une operation
    facturee : l'API ne rend pas le montant debite. `predictions_remaining`
    recopie l'en-tete X-Spavik-Predictions-Remaining (allocation mensuelle
    restante plus solde) ; None quand l'API ne l'envoie pas.
    """

    data: Dict[str, Any] = field(default_factory=dict)
    cost: Optional[int] = 0
    predictions_remaining: Optional[int] = None
    request_id: Optional[str] = None

    @property
    def training_calibration(self) -> Optional[Dict[str, Any]]:
        """Initial test-set diagnostic returned by the performance API."""
        return self.data.get("training_calibration")

    @property
    def engine(self) -> Optional[str]:
        """Exact serving engine, distinct from the model data version."""
        return self.data.get("_engine_version") or self.data.get("engine")

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass
class Prediction(Result):
    @property
    def predictions(self) -> List[Dict[str, Any]]:
        return self.data.get("predictions", [])

    @property
    def version(self) -> Optional[int]:
        return self.data.get("version")


@dataclass
class Forecast(Result):
    """L'API rend la prevision en CSV. La bibliotheque la rend en lignes.

    Le CSV brut reste accessible par `.csv`, pour qui veut l'ecrire tel quel
    dans un fichier.
    """

    @property
    def csv(self) -> str:
        return self.data.get("forecast_csv") or ""

    @property
    def points(self) -> List[Dict[str, Any]]:
        brut = self.csv
        if not brut.strip():
            return self.data.get("forecast") or self.data.get("predictions") or []
        return _data.normaliser(brut, quoi="forecast")

    @property
    def target(self) -> Optional[str]:
        return self.data.get("target")

    @property
    def horizon(self) -> Optional[int]:
        return self.data.get("prediction_length")

    @property
    def series(self) -> Optional[int]:
        return self.data.get("n_series")


def _reste(brut: Mapping[str, Any]) -> Optional[int]:
    """L'en-tete X-Spavik-Predictions-Remaining, recopie par _http. L'API ne
    met pas le solde dans le corps."""
    valeur = brut.get("_predictions_remaining")
    return valeur if isinstance(valeur, int) else None


def _resultat(brut: Optional[Dict[str, Any]], cout: Optional[int], classe: type = Result) -> Any:
    brut = brut or {}
    return classe(data=brut, cost=cout, predictions_remaining=_reste(brut),
                  request_id=brut.get("_request_id"))


def _page(brut: Optional[Dict[str, Any]], limit: int, offset: int):
    """Rend le lot de la page et le prochain offset, ou None quand c'est fini."""
    brut = brut or {}
    lot = brut.get("data") or []
    pagination = brut.get("pagination") or {}
    total = pagination.get("total")
    suivant = offset + len(lot)
    fini = (not lot) or len(lot) < limit or (total is not None and suivant >= total)
    return lot, (None if fini else suivant)


def _refresh_absorbe(exc: _err.SpavikError) -> bool:
    return exc.code == "NO_PENDING_OUTCOMES"


def _model_data(response):
    model = dict(response.get("model") or response)
    if isinstance(response.get("version"), dict):
        model["training"] = response["version"]
    return model


# --------------------------------------------------------------------------
# Modeles
# --------------------------------------------------------------------------

class _ModelBase:
    def __init__(self, client: Any, donnees: Mapping[str, Any]) -> None:
        self._client = client
        self._donnees = dict(donnees)

    @property
    def id(self) -> str:
        return self._donnees["id"]

    @property
    def name(self) -> Optional[str]:
        return self._donnees.get("name")

    @property
    def version(self) -> Optional[int]:
        return self._donnees.get("latest_version") or self._donnees.get("version")

    @property
    def task(self) -> Optional[str]:
        return self._donnees.get("task")

    @property
    def data(self) -> Dict[str, Any]:
        return dict(self._donnees)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id} {self.name!r} version={self.version}>"

    @property
    def engine(self) -> Optional[str]:
        return self._donnees.get("engine")

    @property
    def engine_family(self) -> Optional[str]:
        return self._donnees.get("engine_family")

    @property
    def training(self) -> Optional[Dict[str, Any]]:
        """Initial training diagnostics, including calibration when available."""
        return self._donnees.get("training")

    @property
    def features(self) -> List[str]:
        """Les colonnes que predict doit porter (`feature_columns` chez l'API).
        Vide quand l'API ne les a pas enregistrees."""
        colonnes = self._donnees.get("feature_columns")
        return list(colonnes) if isinstance(colonnes, list) else []


class Model(_ModelBase):
    """Un modele entraine, et les quatre operations qui s'appliquent a lui."""

    def predict(self, rows: Any, *, engine_version: Optional[str] = None) -> Prediction:
        """Score des lignes. Facture, par ligne, les credits du moteur qui sert
        le modele : un sur le moteur par defaut."""
        plan = _ops.predict(self.id, rows, engine_version=engine_version)
        return _resultat(self._client._envoyer(plan.requete), None, Prediction)

    def submit_outcomes(self, outcomes: Any) -> Result:
        """Report observed outcomes. Every outcome requires features and actual. Free."""
        plan = _ops.submit_outcomes(self.id, outcomes)
        return _resultat(self._client._envoyer(plan.requete), 0)

    def refresh(self) -> Optional[Result]:
        """Integre les verites en attente et produit une version.

        Rend `None` quand il n'y a rien a integrer : c'est un etat normal, pas
        une erreur a attraper.
        """
        plan = _ops.refresh(self.id)
        try:
            return _resultat(self._client._envoyer(plan.requete), 0)
        except _err.SpavikError as exc:
            if _refresh_absorbe(exc):
                return None
            raise

    def archive(self) -> None:
        """Archive le modele : il cesse de servir et rend sa place du quota.
        Ses artefacts sont conserves ; `restore` le remet en service. Gratuit."""
        self._client._envoyer(_ops.archive(self.id).requete)

    def restore(self) -> None:
        """Remet en service un modele archive. Il reprend une place du quota. Gratuit."""
        self._client._envoyer(_ops.restore(self.id).requete)

    def performance(self, days: int = 30) -> Optional[Result]:
        """Observed performance and training calibration; API failures are raised."""
        plan = _ops.performance(self.id, days)
        return _resultat(self._client._envoyer(plan.requete), 0)

    def reload(self) -> "Model":
        self._donnees = self._client.model(self.id)._donnees
        return self


class AsyncModel(_ModelBase):
    """Meme objet, memes noms, en asynchrone."""

    async def predict(self, rows: Any, *, engine_version: Optional[str] = None) -> Prediction:
        plan = _ops.predict(self.id, rows, engine_version=engine_version)
        return _resultat(await self._client._envoyer(plan.requete), None, Prediction)

    async def submit_outcomes(self, outcomes: Any) -> Result:
        plan = _ops.submit_outcomes(self.id, outcomes)
        return _resultat(await self._client._envoyer(plan.requete), 0)

    async def refresh(self) -> Optional[Result]:
        plan = _ops.refresh(self.id)
        try:
            return _resultat(await self._client._envoyer(plan.requete), 0)
        except _err.SpavikError as exc:
            if _refresh_absorbe(exc):
                return None
            raise

    async def archive(self) -> None:
        """Voir Model.archive. Gratuit, reversible par restore."""
        await self._client._envoyer(_ops.archive(self.id).requete)

    async def restore(self) -> None:
        """Voir Model.restore. Gratuit."""
        await self._client._envoyer(_ops.restore(self.id).requete)

    async def performance(self, days: int = 30) -> Optional[Result]:
        plan = _ops.performance(self.id, days)
        return _resultat(await self._client._envoyer(plan.requete), 0)

    async def reload(self) -> "AsyncModel":
        frais = await self._client.model(self.id)
        self._donnees = frais._donnees
        return self


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

_REQUETE_FAMILLES = Requete(
    methode="GET", chemin="/v1/engine-families", operation="engine_families",
    delai=15.0, contexte="engine families",
)

_REQUETE_MOTEURS = Requete(
    methode="GET", chemin="/v1/engines", operation="engines",
    delai=15.0, contexte="available engines",
)

# Le solde et la consommation du compte. Lecture gratuite, hors du contrat
# genere (qui ne couvre que les sept operations du moteur), comme les moteurs.
_REQUETE_USAGE = Requete(
    methode="GET", chemin="/v1/usage", operation="usage",
    delai=15.0, contexte="account usage",
)


class Spavik(_Base):
    """Synchronous client. An explicit timeout overrides every operation's
    network timeout, per attempt. Omit it or use None for operation defaults.

    >>> spavik = Spavik()                          # lit SPAVIK_API_KEY
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
        if not self._http_fourni:
            self._http.close()

    def __enter__(self) -> "Spavik":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _envoyer(self, requete: Requete) -> Optional[Dict[str, Any]]:
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

            corps, erreur = interpreter(reponse.status_code, reponse.headers, reponse.text, requete)
            tracer(requete, reponse.status_code, time.monotonic() - debut,
                   _rid(corps, erreur), self.cle_api, tentative)
            if erreur is None:
                return corps
            erreur.idempotency_key = requete.idempotence
            if tentative < self.max_retries and retry_allowed(reponse.status_code, erreur.code, requete.methode, requete.chemin, bool(requete.idempotence)):
                time.sleep(retry_delay(reponse.headers.get("Retry-After"), erreur.code, self.backoff(tentative)))
                continue
            raise erreur

    # -- operations sans modele -------------------------------------------
    def train(self, data: Any, **kw: Any) -> Model:
        """Create and train a model without consuming prediction credits.

        Model state and outcome feedback are functional data, including under
        Zero Data Retention. No additional retention opt-in is required.
        """
        # Les controles locaux d'abord : un refus prononce ici ne doit toucher
        # ni le reseau ni le catalogue des moteurs.
        plan = _ops.train(data, **kw)
        brut = self._envoyer(plan.requete) or {}
        return self._modele(self, _model_data(brut))

    def forecast(self, data: Any, **kw: Any) -> Forecast:
        """Forecast time series. Billed by the API at horizon times the serving engine tariff, all series included."""
        plan = _ops.forecast(data, **kw)
        return _resultat(self._envoyer(plan.requete), plan.cout, Forecast)

    def models(self, *, limit: int = 50, status: Optional[str] = None) -> Iterator[Model]:
        """Parcourt les modeles du workspace, page par page, sans y penser.
        Ceux qui servent par defaut ; status="archived" pour ceux mis de cote."""
        offset: Optional[int] = 0
        while offset is not None:
            plan = _ops.list_models(limit, offset, status)
            lot, offset = _page(self._envoyer(plan.requete), limit, offset)
            for entree in lot:
                yield self._modele(self, entree)

    def archive(self, model_id: str) -> None:
        """Archive un modele par son identifiant, sans le lire d'abord. Voir Model.archive."""
        self._envoyer(_ops.archive(model_id).requete)

    def restore(self, model_id: str) -> None:
        """Remet en service un modele archive, par son identifiant. Sans lecture
        prealable : GET sur un modele archive repond MODEL_ARCHIVED, ce qui
        rendrait la restauration impossible."""
        self._envoyer(_ops.restore(model_id).requete)

    def evaluate(self, data: Any, **kw: Any) -> Dict[str, Any]:
        """Ce que l'entrainement dirait de ces donnees, et ce que le moteur en
        fait a l'essai, sans rien creer ni debiter. Rend le rapport de l'API :
        validation, hint, trial et assessment (status, metric, message),
        transmis sans recalcul ni conclusion de remplacement."""
        brut = self._envoyer(_ops.evaluate(data, **kw).requete)
        return dict(brut) if isinstance(brut, Mapping) else {}

    def backtest(self, data: Any, **kw: Any) -> Dict[str, Any]:
        """Ce que la prevision vaudrait sur cette serie, sans la rendre ni la
        debiter : validation (longueur, pas, doublons), hint, backtest (MASE
        contre les references, note par fenetre), assessment (status, metric,
        message) transmis sans modification."""
        brut = self._envoyer(_ops.backtest(data, **kw).requete)
        return dict(brut) if isinstance(brut, Mapping) else {}

    def model(self, model_id: str) -> Model:
        """Reprend un modele existant par son identifiant."""
        plan = _ops.get_model(model_id)
        brut = self._envoyer(plan.requete) or {}
        return self._modele(self, _model_data(brut))

    def engine_families(self) -> List[Dict[str, Any]]:
        """Families and the default selected by the API. Free."""
        return self._envoyer(_REQUETE_FAMILLES)

    def engines(self) -> List[Dict[str, Any]]:
        """Les moteurs disponibles, tels que l'API les decrit (id, label, status).

        The API selects defaults within the chosen family. Free.
        """
        entrees = self._envoyer(_REQUETE_MOTEURS)
        return [dict(e) for e in entrees if isinstance(e, Mapping)] if isinstance(entrees, list) else []

    def usage(self) -> Dict[str, Any]:
        """Le compte tel que l'API le voit : plan, solde (`credit_balance`),
        alerte de solde bas, periode en cours et consommation ventilee. Gratuit,
        sans effet : a lire avant un lot facture."""
        brut = self._envoyer(_REQUETE_USAGE)
        return dict(brut) if isinstance(brut, Mapping) else {}


class AsyncSpavik(_Base):
    """Asynchronous client, with the same operations and timeout precedence
    as Spavik. Omit timeout or use None for operation defaults."""

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
        if not self._http_fourni:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncSpavik":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _envoyer(self, requete: Requete) -> Optional[Dict[str, Any]]:
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

            corps, erreur = interpreter(reponse.status_code, reponse.headers, reponse.text, requete)
            tracer(requete, reponse.status_code, time.monotonic() - debut,
                   _rid(corps, erreur), self.cle_api, tentative)
            if erreur is None:
                return corps
            erreur.idempotency_key = requete.idempotence
            if tentative < self.max_retries and retry_allowed(reponse.status_code, erreur.code, requete.methode, requete.chemin, bool(requete.idempotence)):
                await asyncio.sleep(retry_delay(reponse.headers.get("Retry-After"), erreur.code, self.backoff(tentative)))
                continue
            raise erreur

    async def train(self, data: Any, **kw: Any) -> AsyncModel:
        """See Spavik.train; model state does not require a retention opt-in."""
        # Les controles locaux d'abord, comme en synchrone.
        plan = _ops.train(data, **kw)
        brut = await self._envoyer(plan.requete) or {}
        return self._modele(self, _model_data(brut))

    async def forecast(self, data: Any, **kw: Any) -> Forecast:
        plan = _ops.forecast(data, **kw)
        return _resultat(await self._envoyer(plan.requete), plan.cout, Forecast)

    async def archive(self, model_id: str) -> None:
        """Voir Spavik.archive."""
        await self._envoyer(_ops.archive(model_id).requete)

    async def restore(self, model_id: str) -> None:
        """Voir Spavik.restore."""
        await self._envoyer(_ops.restore(model_id).requete)

    async def evaluate(self, data: Any, **kw: Any) -> Dict[str, Any]:
        """Voir Spavik.evaluate. Gratuit."""
        brut = await self._envoyer(_ops.evaluate(data, **kw).requete)
        return dict(brut) if isinstance(brut, Mapping) else {}

    async def backtest(self, data: Any, **kw: Any) -> Dict[str, Any]:
        """Voir Spavik.backtest. Gratuit."""
        brut = await self._envoyer(_ops.backtest(data, **kw).requete)
        return dict(brut) if isinstance(brut, Mapping) else {}

    async def models(self, *, limit: int = 50, status: Optional[str] = None) -> AsyncIterator[AsyncModel]:
        offset: Optional[int] = 0
        while offset is not None:
            plan = _ops.list_models(limit, offset, status)
            lot, offset = _page(await self._envoyer(plan.requete), limit, offset)
            for entree in lot:
                yield self._modele(self, entree)

    async def engine_families(self) -> List[Dict[str, Any]]:
        """Families and the default selected by the API. Free."""
        return await self._envoyer(_REQUETE_FAMILLES)

    async def engines(self) -> List[Dict[str, Any]]:
        """Les moteurs disponibles, tels que l'API les decrit (id, label, status)."""
        entrees = await self._envoyer(_REQUETE_MOTEURS)
        return [dict(e) for e in entrees if isinstance(e, Mapping)] if isinstance(entrees, list) else []

    async def usage(self) -> Dict[str, Any]:
        """Voir Spavik.usage : plan, solde, periode, consommation. Gratuit."""
        brut = await self._envoyer(_REQUETE_USAGE)
        return dict(brut) if isinstance(brut, Mapping) else {}

    async def model(self, model_id: str) -> AsyncModel:
        plan = _ops.get_model(model_id)
        brut = await self._envoyer(plan.requete) or {}
        return self._modele(self, _model_data(brut))


def _rid(corps: Any, erreur: Optional[_err.SpavikError]) -> Optional[str]:
    if isinstance(corps, dict):
        return corps.get("_request_id")
    return erreur.request_id if erreur else None
