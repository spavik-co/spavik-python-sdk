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
from . import errors as _err
from ._http import Requete, _Base, attente, interpreter, reprenable, tracer


# --------------------------------------------------------------------------
# Resultats
# --------------------------------------------------------------------------

@dataclass
class Resultat:
    """Ce que rend un appel : les donnees brutes, et ce qui aide a s'y retrouver."""

    donnees: Dict[str, Any] = field(default_factory=dict)
    cout: int = 0
    solde: Optional[int] = None
    request_id: Optional[str] = None

    def __getitem__(self, cle: str) -> Any:
        return self.donnees[cle]

    def get(self, cle: str, defaut: Any = None) -> Any:
        return self.donnees.get(cle, defaut)


@dataclass
class Prediction(Resultat):
    @property
    def lignes(self) -> List[Dict[str, Any]]:
        return self.donnees.get("predictions", [])

    @property
    def version(self) -> Optional[int]:
        return self.donnees.get("version")


@dataclass
class Prevision(Resultat):
    """L'API rend la prevision en CSV. La bibliotheque la rend en lignes.

    Le CSV brut reste accessible par `.csv`, pour qui veut l'ecrire tel quel
    dans un fichier.
    """

    @property
    def csv(self) -> str:
        return self.donnees.get("forecast_csv") or ""

    @property
    def points(self) -> List[Dict[str, Any]]:
        brut = self.csv
        if not brut.strip():
            return self.donnees.get("forecast") or self.donnees.get("predictions") or []
        return _data.normaliser(brut, quoi="forecast")

    @property
    def cible(self) -> Optional[str]:
        return self.donnees.get("target")

    @property
    def horizon(self) -> Optional[int]:
        return self.donnees.get("prediction_length")

    @property
    def series(self) -> Optional[int]:
        return self.donnees.get("n_series")


def _solde(brut: Mapping[str, Any]) -> Optional[int]:
    """Le solde voyage avec la reponse quand l'API le rend, sous l'un de ces noms."""
    for cle in ("credits_remaining", "balance", "credit_balance", "credits"):
        valeur = brut.get(cle)
        if isinstance(valeur, int):
            return valeur
    facturation = brut.get("billing")
    if isinstance(facturation, Mapping):
        for cle in ("credits_remaining", "balance", "credit_balance"):
            valeur = facturation.get(cle)
            if isinstance(valeur, int):
                return valeur
    # Sinon l'en-tete X-Spavik-Predictions-Remaining, recopie par _http.
    valeur = brut.get("_predictions_remaining")
    return valeur if isinstance(valeur, int) else None


def _resultat(brut: Optional[Dict[str, Any]], cout: int, classe: type = Resultat) -> Any:
    brut = brut or {}
    return classe(donnees=brut, cout=cout, solde=_solde(brut),
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


def _prix_du_moteur(entrees: Any, moteur: Optional[str]) -> int:
    """Les credits que coute une prediction sur ce moteur, 1 si le catalogue
    ne le dit pas. Le prix est publie par /v1/engines (`credits`)."""
    if not moteur or not isinstance(entrees, list):
        return 1
    for entree in entrees:
        if isinstance(entree, Mapping) and entree.get("id") == moteur:
            credits = entree.get("credits")
            return credits if isinstance(credits, int) and credits > 0 else 1
    return 1


def _moteur_par_defaut(entrees: Any) -> Optional[str]:
    """Le moteur marque `default`, sinon le premier de la liste."""
    if not isinstance(entrees, list) or not entrees:
        return None
    for entree in entrees:
        if isinstance(entree, Mapping) and entree.get("status") == "default":
            return entree.get("id")
    premier = entrees[0]
    return premier.get("id") if isinstance(premier, Mapping) else None


def _refresh_absorbe(exc: _err.SpavikError) -> bool:
    """Rien a integrer, integration en cours, stockage absent : etats normaux."""
    if isinstance(exc, _err.SpavikUnavailable):
        return True
    return isinstance(exc, _err.SpavikConflict) and exc.code in {
        "NO_PENDING_OUTCOMES", "REFRESH_IN_PROGRESS"}


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
    def donnees(self) -> Dict[str, Any]:
        return dict(self._donnees)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id} {self.name!r} version={self.version}>"

    @property
    def engine(self) -> Optional[str]:
        return self._donnees.get("engine")

    @property
    def features(self) -> List[str]:
        """Les colonnes que predict doit porter (`feature_columns` chez l'API).
        Vide quand l'API ne les a pas enregistrees."""
        colonnes = self._donnees.get("feature_columns")
        return list(colonnes) if isinstance(colonnes, list) else []


class Model(_ModelBase):
    """Un modele entraine, et les quatre operations qui s'appliquent a lui."""

    def predict(self, rows: Any) -> Prediction:
        """Score des lignes. Facture, par ligne, les credits du moteur qui sert
        le modele : un sur le moteur par defaut."""
        plan = _ops.predict(self.id, rows)
        cout = plan.cout * self._client._prix(self.engine)
        return _resultat(self._client._envoyer(plan.requete), cout, Prediction)

    def submit_outcomes(self, outcomes: Any) -> Resultat:
        """Remonte ce qui est reellement arrive. Gratuit."""
        plan = _ops.submit_outcomes(self.id, outcomes)
        return _resultat(self._client._envoyer(plan.requete), 0)

    def refresh(self) -> Optional[Resultat]:
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

    def predictions(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Les dernieres predictions servies par ce modele, avec leur request_id,
        pour rattacher des verites ensuite. Gratuit. Vide tant que le journal
        n'est pas en place."""
        brut = self._client._envoyer(_ops.predictions(self.id, limit).requete)
        return [dict(e) for e in brut if isinstance(e, Mapping)] if isinstance(brut, list) else []

    def archive(self) -> None:
        """Archive le modele : il cesse de servir et rend sa place du quota.
        Ses artefacts sont conserves ; `restore` le remet en service. Gratuit."""
        self._client._envoyer(_ops.archive(self.id).requete)

    def restore(self) -> None:
        """Remet en service un modele archive. Il reprend une place du quota. Gratuit."""
        self._client._envoyer(_ops.restore(self.id).requete)

    def performance(self, days: int = 30) -> Optional[Resultat]:
        """Performance constatee. `None` si le journal analytique n'est pas en place."""
        plan = _ops.performance(self.id, days)
        try:
            return _resultat(self._client._envoyer(plan.requete), 0)
        except _err.SpavikUnavailable:
            return None

    def reload(self) -> "Model":
        self._donnees = self._client.model(self.id)._donnees
        return self


class AsyncModel(_ModelBase):
    """Meme objet, memes noms, en asynchrone."""

    async def predict(self, rows: Any) -> Prediction:
        plan = _ops.predict(self.id, rows)
        cout = plan.cout * await self._client._prix(self.engine)
        return _resultat(await self._client._envoyer(plan.requete), cout, Prediction)

    async def submit_outcomes(self, outcomes: Any) -> Resultat:
        plan = _ops.submit_outcomes(self.id, outcomes)
        return _resultat(await self._client._envoyer(plan.requete), 0)

    async def refresh(self) -> Optional[Resultat]:
        plan = _ops.refresh(self.id)
        try:
            return _resultat(await self._client._envoyer(plan.requete), 0)
        except _err.SpavikError as exc:
            if _refresh_absorbe(exc):
                return None
            raise

    async def predictions(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Voir Model.predictions. Gratuit."""
        brut = await self._client._envoyer(_ops.predictions(self.id, limit).requete)
        return [dict(e) for e in brut if isinstance(e, Mapping)] if isinstance(brut, list) else []

    async def archive(self) -> None:
        """Voir Model.archive. Gratuit, reversible par restore."""
        await self._client._envoyer(_ops.archive(self.id).requete)

    async def restore(self) -> None:
        """Voir Model.restore. Gratuit."""
        await self._client._envoyer(_ops.restore(self.id).requete)

    async def performance(self, days: int = 30) -> Optional[Resultat]:
        plan = _ops.performance(self.id, days)
        try:
            return _resultat(await self._client._envoyer(plan.requete), 0)
        except _err.SpavikUnavailable:
            return None

    async def reload(self) -> "AsyncModel":
        frais = await self._client.model(self.id)
        self._donnees = frais._donnees
        return self


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

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
    """Client synchrone.

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
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: Optional[Any] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, backoff)
        self._http = client or httpx.Client(timeout=timeout)
        self._http_fourni = client is not None
        self._moteur_defaut: Optional[str] = None
        self._moteurs: Optional[list] = None

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
                    headers=requete.entetes(self.cle_api),
                    json=requete.corps, params=requete.parametres, timeout=requete.delai,
                )
            except httpx.HTTPError as exc:
                tracer(requete, None, time.monotonic() - debut, None, self.cle_api, tentative)
                if reprenable(None, tentative, self.max_retries):
                    time.sleep(self.backoff(tentative))
                    continue
                raise _err.SpavikTransportError(
                    f"{requete.contexte or requete.operation}: {type(exc).__name__}: {exc}"
                ) from exc

            corps, erreur = interpreter(reponse.status_code, reponse.headers, reponse.text, requete)
            tracer(requete, reponse.status_code, time.monotonic() - debut,
                   _rid(corps, erreur), self.cle_api, tentative)
            if erreur is None:
                return corps
            if reprenable(reponse.status_code, tentative, self.max_retries):
                time.sleep(self.backoff(tentative))
                continue
            raise erreur

    # -- operations sans modele -------------------------------------------
    def _moteur(self) -> Optional[str]:
        """Resout le moteur par defaut, une seule fois par client.

        L'API exige `engine` a la creation, alors que le contrat ne le compte pas
        parmi les champs requis. Plutot que d'imposer a l'appelant de connaitre
        le catalogue des moteurs des sa premiere ligne de code, on va le lire :
        la route est publique, gratuite, et la reponse est mise de cote.
        """
        if self._moteur_defaut is not None:
            return self._moteur_defaut or None
        self._moteur_defaut = _moteur_par_defaut(self._catalogue()) or ""
        return self._moteur_defaut or None

    def _catalogue(self) -> list:
        """Le catalogue des moteurs, lu une fois par client. Vide si l'API ne
        repond pas : elle dira elle-meme ce qui manque, et elle le dit bien."""
        if self._moteurs is None:
            try:
                entrees = self._envoyer(_REQUETE_MOTEURS)
                self._moteurs = entrees if isinstance(entrees, list) else []
            except _err.SpavikError:
                self._moteurs = []
        return self._moteurs

    def _prix(self, moteur: Optional[str]) -> int:
        """Credits par prediction sur ce moteur. Sans moteur connu, 1, sans appel."""
        return _prix_du_moteur(self._catalogue(), moteur) if moteur else 1

    def train(self, data: Any, **kw: Any) -> Model:
        """Cree un modele et l'entraine, en un appel. Apprendre ne coute rien."""
        # Les controles locaux d'abord : un refus prononce ici ne doit toucher
        # ni le reseau ni le catalogue des moteurs.
        plan = _ops.train(data, **kw)
        if not plan.requete.corps.get("engine"):
            moteur = self._moteur()
            if moteur:
                plan.requete.corps["engine"] = moteur
        brut = self._envoyer(plan.requete) or {}
        return self._modele(self, brut.get("model") or brut)

    def forecast(self, data: Any, **kw: Any) -> Prevision:
        """Forecast time series. One credit per requested horizon step per call."""
        plan = _ops.forecast(data, **kw)
        return _resultat(self._envoyer(plan.requete), plan.cout, Prevision)

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
        return self._modele(self, brut.get("model") or brut)

    def engines(self) -> List[Dict[str, Any]]:
        """Les moteurs disponibles, tels que l'API les decrit (id, label, status).

        Celui dont le `status` vaut `default` est pris quand `train` ne recoit
        pas de moteur. Gratuit.
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
    """Client asynchrone. Memes noms, memes refus, memes resultats."""

    _modele = AsyncModel

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: Optional[Any] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, backoff)
        self._http = client or httpx.AsyncClient(timeout=timeout)
        self._http_fourni = client is not None
        self._moteur_defaut: Optional[str] = None
        self._moteurs: Optional[list] = None

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
                    headers=requete.entetes(self.cle_api),
                    json=requete.corps, params=requete.parametres, timeout=requete.delai,
                )
            except httpx.HTTPError as exc:
                tracer(requete, None, time.monotonic() - debut, None, self.cle_api, tentative)
                if reprenable(None, tentative, self.max_retries):
                    await asyncio.sleep(self.backoff(tentative))
                    continue
                raise _err.SpavikTransportError(
                    f"{requete.contexte or requete.operation}: {type(exc).__name__}: {exc}"
                ) from exc

            corps, erreur = interpreter(reponse.status_code, reponse.headers, reponse.text, requete)
            tracer(requete, reponse.status_code, time.monotonic() - debut,
                   _rid(corps, erreur), self.cle_api, tentative)
            if erreur is None:
                return corps
            if reprenable(reponse.status_code, tentative, self.max_retries):
                await asyncio.sleep(self.backoff(tentative))
                continue
            raise erreur

    async def _moteur(self) -> Optional[str]:
        """Voir Spavik._moteur : meme raison, meme mise de cote."""
        if self._moteur_defaut is not None:
            return self._moteur_defaut or None
        self._moteur_defaut = _moteur_par_defaut(await self._catalogue()) or ""
        return self._moteur_defaut or None

    async def _catalogue(self) -> list:
        if self._moteurs is None:
            try:
                entrees = await self._envoyer(_REQUETE_MOTEURS)
                self._moteurs = entrees if isinstance(entrees, list) else []
            except _err.SpavikError:
                self._moteurs = []
        return self._moteurs

    async def _prix(self, moteur: Optional[str]) -> int:
        return _prix_du_moteur(await self._catalogue(), moteur) if moteur else 1

    async def train(self, data: Any, **kw: Any) -> AsyncModel:
        # Les controles locaux d'abord, comme en synchrone.
        plan = _ops.train(data, **kw)
        if not plan.requete.corps.get("engine"):
            moteur = await self._moteur()
            if moteur:
                plan.requete.corps["engine"] = moteur
        brut = await self._envoyer(plan.requete) or {}
        return self._modele(self, brut.get("model") or brut)

    async def forecast(self, data: Any, **kw: Any) -> Prevision:
        plan = _ops.forecast(data, **kw)
        return _resultat(await self._envoyer(plan.requete), plan.cout, Prevision)

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
        return self._modele(self, brut.get("model") or brut)


def _rid(corps: Any, erreur: Optional[_err.SpavikError]) -> Optional[str]:
    if isinstance(corps, dict):
        return corps.get("_request_id")
    return erreur.request_id if erreur else None
