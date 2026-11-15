"""Robustesse des entrees, du transport et des retours, observee a la frontiere HTTP."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import inspect
import json
import time
import typing
from decimal import Decimal

import httpx
import pytest

from api_simulee import CLE
from spavik import (
    AsyncSpavik,
    Spavik,
    SpavikAuthError,
    SpavikConflict,
    SpavikDataError,
    SpavikError,
    SpavikRateLimited,
    SpavikSignatureError,
    verify,
)
from spavik._data import normaliser


def client_simule(handler, cle="fixture", **options):
    return Spavik(cle, base_url="http://api.test", backoff=lambda _: 0,
                  client=httpx.Client(transport=httpx.MockTransport(handler)), **options)


# -- valeurs non JSON ------------------------------------------------

def test_listes_de_dicts_avec_dates_decimaux_et_manquants():
    lignes = normaliser([{
        "jour": dt.date(2026, 7, 1), "quand": dt.datetime(2026, 7, 1, 8, 30),
        "prix": Decimal("12.50"), "vide": float("nan"), "loin": float("inf"),
        "texte": "ok", "imbrique": {"d": dt.date(2026, 1, 2), "n": float("nan")},
    }])
    assert lignes == [{
        "jour": "2026-07-01", "quand": "2026-07-01T08:30:00", "prix": 12.5,
        "vide": None, "loin": None, "texte": "ok",
        "imbrique": {"d": "2026-01-02", "n": None},
    }]
    json.dumps(lignes, allow_nan=False)


def test_valeur_non_serialisable_nomme_la_colonne():
    with pytest.raises(SpavikDataError, match="column 'blob' holds a object value"):
        normaliser([{"ok": 1, "blob": object()}], quoi="training data")


def test_dataframe_avec_dates_et_manquants():
    pandas = pytest.importorskip("pandas")
    df = pandas.read_csv(__import__("io").StringIO("date,ventes\n2026-07-01,3\n2026-07-02,\n"),
                         parse_dates=["date"])
    df["n"] = pandas.array([1, None], dtype="Int64")
    df["t"] = [pandas.Timestamp("2026-07-03"), pandas.NaT]
    lignes = normaliser(df)
    assert lignes == [
        {"date": "2026-07-01T00:00:00", "ventes": 3.0, "n": 1, "t": "2026-07-03T00:00:00"},
        {"date": "2026-07-02T00:00:00", "ventes": None, "n": None, "t": None},
    ]
    json.dumps(lignes, allow_nan=False)


# -- pagination ------------------------------------------------------

@pytest.mark.parametrize("limit", [500, 50, 200])
def test_pagination_au_dela_de_200(spavik, api, limit):
    api.modeles = {f"mdl_{i:04d}": {"id": f"mdl_{i:04d}"} for i in range(450)}
    assert len(list(spavik.models(limit=limit))) == 450
    limites = {int(a.url.params["limit"]) for a in api.appels}
    assert max(limites) <= 200


def test_pagination_s_arrete_sur_has_more():
    pages = []

    def handler(requete):
        pages.append(requete)
        return httpx.Response(200, json={"data": [{"id": "mdl_1"}],
                                         "pagination": {"has_more": False}})
    assert len(list(client_simule(handler).models(limit=1))) == 1
    assert len(pages) == 1


# -- SPAVIK_BASE_URL a la construction --------------------------------

def test_base_url_lue_a_la_construction(monkeypatch):
    monkeypatch.setenv("SPAVIK_BASE_URL", "https://test-api.spavik.co/")
    assert Spavik("k").base_url == "https://test-api.spavik.co"
    assert AsyncSpavik("k").base_url == "https://test-api.spavik.co"
    assert Spavik("k", base_url="https://autre.test").base_url == "https://autre.test"
    monkeypatch.delenv("SPAVIK_BASE_URL")
    assert Spavik("k").base_url == "https://api.spavik.co"


# -- signatures explicites --------------------------------------------

@pytest.mark.parametrize("classe", [Spavik, AsyncSpavik])
@pytest.mark.parametrize("methode", ["train", "forecast", "evaluate", "backtest"])
def test_signatures_explicites(classe, methode):
    parametres = inspect.signature(getattr(classe, methode)).parameters
    assert not any(p.kind is p.VAR_KEYWORD for p in parametres.values())
    assert parametres["target"].kind is inspect.Parameter.KEYWORD_ONLY


def test_retours_types():
    assert typing.get_type_hints(Spavik.evaluate)["return"].__name__ == "EvaluationReport"
    assert typing.get_type_hints(Spavik.backtest)["return"].__name__ == "BacktestReport"
    assert typing.get_type_hints(Spavik.usage)["return"].__name__ == "Usage"


# -- secret de webhook ------------------------------------------------

@pytest.mark.parametrize("secret", ["", None])
def test_verify_refuse_un_secret_vide(secret):
    corps = b'{"type":"model.trained"}'
    t = int(time.time())
    signature = hmac.new(b"", f"{t}.".encode() + corps, hashlib.sha256).hexdigest()
    with pytest.raises(SpavikSignatureError, match="missing webhook secret"):
        verify(corps, {"Spavik-Signature": f"t={t},v1={signature}"}, secret)


# -- cle d'idempotence de l'appelant -----------------------------------

def test_cle_d_idempotence_fournie_et_rejouee(spavik, api, churn):
    api.repondra("/v1/models", httpx.Response(503, json={"message": "ENGINE_UNAVAILABLE"},
                                              headers={"Retry-After": "0"}))
    model = spavik.train(churn, target="churn", idempotency_key="cle-train")
    model.predict([{"plan": "pro"}], idempotency_key="cle-predict")
    serie = [{"ventes": i} for i in range(28)]
    spavik.forecast(serie, target="ventes", horizon=3, idempotency_key="cle-forecast")
    model.submit_outcomes([{"features": {"plan": "pro"}, "actual": 1}], idempotency_key="cle-outcomes")
    model.refresh(idempotency_key="cle-refresh")
    cles = [a.headers.get("Idempotency-Key") for a in api.appels if a.method == "POST"]
    assert cles == ["cle-train", "cle-train", "cle-predict", "cle-forecast",
                    "cle-outcomes", "cle-refresh"]


# -- evaluate ---------------------------------------------------------

def test_evaluate_n_envoie_plus_engine_family(spavik, api, churn):
    with pytest.raises(TypeError):
        spavik.evaluate(churn, target="churn", engine_family="presage")
    spavik.evaluate(churn, target="churn", task="regression", max_samples=50)
    corps = json.loads(api.appels[-1].content)
    assert corps["task"] == "regression" and corps["max_samples"] == 50
    assert "engine_family" not in corps


# -- Retry-After plafonne ---------------------------------------------

def test_retry_after_trop_long_rend_la_main(monkeypatch):
    attentes, appels = [], []
    monkeypatch.setattr("spavik.client.time.sleep", attentes.append)

    def handler(requete):
        appels.append(requete)
        return httpx.Response(429, json={"message": "TOO_MANY_REQUESTS"},
                              headers={"Retry-After": "3600"})
    with pytest.raises(SpavikRateLimited):
        client_simule(handler).usage()
    assert len(appels) == 1 and attentes == []


def test_retry_after_d_une_minute_est_attendu(monkeypatch):
    attentes, appels = [], []
    monkeypatch.setattr("spavik.client.time.sleep", attentes.append)

    def handler(requete):
        appels.append(requete)
        if len(appels) == 1:
            return httpx.Response(429, json={"message": "TOO_MANY_REQUESTS"},
                                  headers={"Retry-After": "60"})
        return httpx.Response(200, json={"plan": "free"})
    assert client_simule(handler).usage() == {"plan": "free"}
    assert attentes == [60.0]


# -- cle absente -----------------------------------------------------

async def test_sans_cle_refus_local_sauf_routes_publiques(monkeypatch):
    monkeypatch.delenv("SPAVIK_API_KEY", raising=False)
    appels = []

    def handler(requete):
        appels.append(requete)
        return httpx.Response(200, json=[{"id": "presage"}])
    client = client_simule(handler, cle=None)
    with pytest.raises(SpavikAuthError) as exc:
        client.usage()
    assert str(exc.value) == "no API key: set SPAVIK_API_KEY or pass api_key. Nothing was sent."
    assert appels == []
    assert client.engine_families() == [{"id": "presage"}]
    assert client.engines() == [{"id": "presage"}]
    assert all("X-Spavik-Api-Key" not in a.headers for a in appels)

    aclient = AsyncSpavik("", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(SpavikAuthError, match="no API key"):
        await aclient.evaluate([{"x": 1}], target="x")
    assert len(appels) == 2


def test_token_invalid_est_une_erreur_d_authentification():
    def handler(requete):
        return httpx.Response(401, json={"message": "TOKEN_INVALID",
                                         "messageDetail": "Access token is invalid or expired."})
    with pytest.raises(SpavikAuthError) as exc:
        client_simule(handler).usage()
    assert exc.value.code == "TOKEN_INVALID"


# -- identifiant encode ----------------------------------------------

def test_identifiant_de_modele_encode():
    chemins = []

    def handler(requete):
        chemins.append(requete.url.raw_path.decode())
        return httpx.Response(200, json={"model": {"id": "x"}})
    client = client_simule(handler)
    client.model("../usage")
    client.model("mdl_1?status=archived")
    assert chemins == ["/v1/models/..%2Fusage", "/v1/models/mdl_1%3Fstatus%3Darchived"]


# -- pas de cles internes dans les retours ----------------------------

def test_pas_de_cles_internes(spavik, api, churn):
    assert not [k for k in spavik.usage() if k.startswith("_")]
    assert not [k for k in spavik.evaluate(churn, target="churn") if k.startswith("_")]
    model = spavik.train(churn, target="churn")
    assert not [k for k in model.data if k.startswith("_")]
    resultat = model.predict([{"plan": "pro"}])
    assert not [k for k in resultat.data if k.startswith("_")]
    assert resultat.request_id == "req_simule200"
    assert resultat.predictions_remaining == 99


def test_engine_version_vient_de_l_en_tete():
    def handler(requete):
        return httpx.Response(200, json={"model": {"id": "mdl_1"}} if requete.method == "GET"
                              else {"predictions": []},
                              headers={"X-Spavik-Model-Version": "presage-2"})
    resultat = client_simule(handler).model("mdl_1").predict([{"x": 1}])
    assert resultat.engine_version == "presage-2" and resultat.engine == "presage-2"
    assert resultat.data == {"predictions": []}


# -- en-tetes CSV ----------------------------------------------------

def test_en_tetes_csv_sans_espaces_de_bord():
    assert normaliser("plan , seats\npro,12\n") == [{"plan": "pro", "seats": 12}]
    with pytest.raises(SpavikDataError, match="unique"):
        normaliser("plan,plan \npro,free\n")


# -- asymetries ------------------------------------------------------

def test_restore_rend_le_modele(spavik, api, churn):
    model = spavik.train(churn, target="churn")
    model.archive()
    restaure = spavik.restore(model.id)
    assert restaure.id == model.id and restaure.data["status"] == "ready"
    model.archive()
    assert model.restore() is model and model.data["status"] == "ready"


@pytest.mark.parametrize("horizon", [7.5, "7", True])
def test_horizon_non_entier_refuse(spavik, api, horizon):
    serie = [{"ventes": i} for i in range(28)]
    with pytest.raises(SpavikDataError, match=f"the horizon must be at least 1, got {horizon}."):
        spavik.forecast(serie, target="ventes", horizon=horizon)
    with pytest.raises(SpavikDataError, match="Nothing was sent"):
        spavik.backtest(serie, target="ventes", horizon=horizon)
    assert api.appels == []


def test_forecast_backtest():
    def handler(requete):
        return httpx.Response(200, json={"forecast_csv": "y\n1\n", "backtest": {"metrics": {"MASE": 0.5}}})
    assert client_simule(handler).forecast([{"y": 1}], target="y", horizon=1).backtest == {
        "metrics": {"MASE": 0.5}}


# -- controles ------------------------------------------------------

def test_serie_courte_par_item_id(spavik, api):
    serie = [{"boutique": "a", "ventes": i} for i in range(20)]
    serie += [{"boutique": "b", "ventes": i} for i in range(3)]
    with pytest.raises(SpavikDataError, match="the series 'b' has 3 point"):
        spavik.forecast(serie, target="ventes", horizon=7, item_id="boutique")
    with pytest.raises(SpavikDataError, match="item_id column 'magasin' is missing"):
        spavik.forecast(serie, target="ventes", horizon=7, item_id="magasin")
    assert api.appels == []


def test_engine_retired_est_un_conflit(spavik, api, churn):
    model = spavik.train(churn, target="churn")
    api.repondra(f"/v1/models/{model.id}/predict", httpx.Response(
        410, json={"message": "ENGINE_RETIRED", "messageDetail": "Engine 'presage-1' has been retired."}))
    with pytest.raises(SpavikConflict) as exc:
        model.predict([{"plan": "pro"}], engine_version="presage-1")
    assert exc.value.code == "ENGINE_RETIRED" and exc.value.status == 410


@pytest.mark.parametrize("corps", [{}, {"model": {"name": "sans id"}}])
def test_reponse_201_sans_identifiant(churn, corps):
    def handler(requete):
        return httpx.Response(201, json=corps, headers={"X-Spavik-Request-Id": "req_vide"})
    with pytest.raises(SpavikError, match="training: the API response carries no model id") as exc:
        client_simule(handler).train(churn, target="churn")
    assert exc.value.request_id == "req_vide"


# -- archive et restore sans Idempotency-Key ------------------------

def test_archive_et_restore_sans_cle_d_idempotence(spavik, api, churn):
    model = spavik.train(churn, target="churn")
    model.archive()
    spavik.restore(model.id)
    for appel in api.appels:
        if appel.url.path.endswith(("/archive", "/restore")):
            assert "Idempotency-Key" not in appel.headers


def test_docstrings_publiques_en_anglais():
    import spavik as paquet

    import re

    francais = re.compile(r"\b(les|des|une|est|modele|donnees|lignes|appel|avec|pour|sur|rend)\b")
    for nom in paquet.__all__:
        objet = getattr(paquet, nom)
        if not inspect.isclass(objet) and not inspect.isfunction(objet):
            continue
        membres = [objet] + [m for _, m in inspect.getmembers(objet)
                             if callable(m) or isinstance(m, property)]
        for membre in membres:
            nom_membre = getattr(membre, "__name__", "")
            if nom_membre.startswith("_") and membre is not objet:
                continue
            texte = (inspect.getdoc(membre) or "").lower()
            assert not francais.search(texte), (nom, nom_membre, texte[:80])


def test_cle_fixture_reste_la_cle_de_test():
    assert CLE.startswith("sk-spv-api-TEST")
