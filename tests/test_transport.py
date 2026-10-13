"""Transport : erreurs typees, reprises, idempotence, reponses illisibles."""

from __future__ import annotations

import httpx
import pytest

from spavik import (
    SpavikCreditsExhausted,
    SpavikNotFound,
    SpavikRateLimited,
    SpavikTransportError,
    SpavikValidationError,
)


def _erreur(statut, code, **extra):
    corps = {"status": "error", "message": code, "messageDetail": "detail", **extra}
    return httpx.Response(statut, json=corps, headers={"x-request-id": "req_abc123"})


def test_le_request_id_remonte_dans_l_exception(spavik, api, churn):
    api.repondra("/v1/models", _erreur(422, "TARGET_COLUMN_MISSING"))
    with pytest.raises(SpavikValidationError) as exc:
        spavik.train(churn, target="churn")
    assert exc.value.request_id == "req_abc123"
    assert exc.value.code == "TARGET_COLUMN_MISSING"
    assert "req_abc123" in str(exc.value)


def test_credits_epuises_porte_le_solde(spavik, api, churn):
    modele = spavik.train(churn, target="churn")
    api.solde = 2
    with pytest.raises(SpavikCreditsExhausted) as exc:
        modele.predict([{"plan": "pro"}] * 5)
    assert exc.value.balance == 2
    assert exc.value.required == 5
    assert exc.value.code == "CREDITS_EXHAUSTED"


def test_reponse_html_ne_leve_pas_une_erreur_de_decodage(spavik, api, churn):
    """Une route inconnue rend du HTML : l'appelant doit voir une erreur nommee."""
    modele = spavik.train(churn, target="churn")
    api.repondra("/v1/models/mdl_test0001/predict", httpx.Response(
        404, text="<!DOCTYPE html><html><body><pre>Cannot POST</pre></body></html>",
        headers={"content-type": "text/html; charset=utf-8", "x-request-id": "req_html"}))
    with pytest.raises(SpavikTransportError) as exc:
        modele.predict([{"plan": "pro"}])
    assert "non-JSON" in str(exc.value)
    assert exc.value.request_id == "req_html"


def test_reprise_sur_500_puis_succes(spavik, api, churn):
    api.repondra("/v1/models", _erreur(500, "INTERNAL_ERROR"))
    modele = spavik.train(churn, target="churn")
    assert modele.id
    assert api.compte("/v1/models") == 2


def test_pas_de_reprise_sur_4xx(spavik, api, churn):
    api.repondra("/v1/models", _erreur(422, "VALIDATION_ERROR"))
    with pytest.raises(SpavikValidationError):
        spavik.train(churn, target="churn")
    assert api.compte("/v1/models") == 1


def test_reprise_sur_429(spavik, api, churn):
    api.repondra("/v1/models", _erreur(429, "TOO_MANY_REQUESTS"))
    spavik.train(churn, target="churn")
    assert api.compte("/v1/models") == 2


def test_abandon_apres_trois_tentatives(spavik, api, churn):
    api.repondra("/v1/models", *[_erreur(503, "ENGINE_UNAVAILABLE") for _ in range(5)])
    with pytest.raises(Exception):
        spavik.train(churn, target="churn")
    assert api.compte("/v1/models") == 3


def test_reprise_reseau(spavik, api, churn):
    api.repondra("/v1/models", httpx.ConnectTimeout("le reseau a lache"))
    modele = spavik.train(churn, target="churn")
    assert modele.id
    assert api.compte("/v1/models") == 2


def test_la_reprise_rejoue_la_meme_cle_d_idempotence(spavik, api, churn):
    """Le point qui evite un second debit : la cle ne change pas entre deux tentatives."""
    api.repondra("/v1/models", _erreur(503, "ENGINE_UNAVAILABLE"))
    spavik.train(churn, target="churn")
    cles = [a.headers.get("Idempotency-Key") for a in api.appels
            if a.url.path == "/v1/models"]
    assert len(cles) == 2
    assert cles[0] == cles[1]
    assert cles[0]


def test_une_prediction_rejouee_ne_debite_pas_deux_fois(spavik, api, churn):
    """La reprise apres 503 ne doit pas facturer les lignes deux fois."""
    modele = spavik.train(churn, target="churn")
    depart = api.solde
    api.repondra(f"/v1/models/{modele.id}/predict", _erreur(503, "ENGINE_UNAVAILABLE"))
    resultat = modele.predict([{"plan": "pro"}] * 4)
    assert resultat.cout == 4
    assert depart - api.solde == 4


def test_chaque_appel_a_sa_propre_cle(spavik, api, churn):
    spavik.train(churn, target="churn")
    spavik.train(churn, target="churn")
    cles = {a.headers.get("Idempotency-Key") for a in api.appels
            if a.url.path == "/v1/models" and a.method == "POST"}
    assert len(cles) == 2


def test_les_lectures_ne_portent_pas_de_cle(spavik, api, churn):
    spavik.train(churn, target="churn")
    list(spavik.models())
    lectures = [a for a in api.appels if a.method == "GET"]
    assert lectures
    assert all(a.headers.get("Idempotency-Key") is None for a in lectures)


def test_modele_inexistant(spavik):
    with pytest.raises(SpavikNotFound) as exc:
        spavik.model("mdl_inexistant")
    assert exc.value.code == "MODEL_NOT_FOUND"


def test_cle_invalide(api, churn):
    from spavik import Spavik, SpavikAuthError

    client = Spavik("sk-spv-api-wrong", base_url="http://api.test", backoff=lambda _: 0,
                    client=httpx.Client(transport=httpx.MockTransport(api)))
    with pytest.raises(SpavikAuthError) as exc:
        client.train(churn, target="churn")
    assert exc.value.code == "API_KEY_INVALID"


def test_erreur_de_la_passerelle_nest_pas_prise_pour_un_code(spavik, api, churn):
    """La passerelle rend ses propres erreurs, hors enveloppe de l'API.

    {"code": 404, "message": "The current request is not defined by this API."}
    Cette phrase ne doit pas devenir le code machine de l'exception.
    """
    api.repondra("/v1/models", httpx.Response(
        404, json={"code": 404, "message": "The current request is not defined by this API."},
        headers={"x-request-id": "req_gw"}))
    with pytest.raises(SpavikNotFound) as exc:
        spavik.train(churn, target="churn")
    assert exc.value.code is None
    assert "not defined by this API" in str(exc.value)
    assert exc.value.request_id == "req_gw"
