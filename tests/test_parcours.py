"""La boucle complete, et l'equivalence entre synchrone et asynchrone."""

from __future__ import annotations

import pytest

from spavik import SpavikError


def test_boucle_complete(spavik, api, churn):
    modele = spavik.train(churn, target="churn")
    assert modele.id.startswith("mdl_")
    assert modele.version == 1

    depart = api.solde
    prediction = modele.predict([{"plan": "pro", "seats": 12, "tickets_90d": 3}])
    assert prediction.cout is None
    assert prediction.solde == depart - 1
    assert len(prediction.lignes) == 1
    assert prediction.request_id

    verites = modele.submit_outcomes([
        {"request_id": "req_1", "actual": 1},
        {"request_id": "req_2", "actual": 0},
        {"request_id": "req_3", "actual": 1},
    ])
    assert verites["accepted"] == 3
    assert verites.cout == 0

    integration = modele.refresh()
    assert integration is not None
    assert integration["version"]["version"] == 2
    assert integration["outcomes_applied"] == 3

    perf = modele.performance(days=30)
    assert perf is not None
    assert perf["observed"]["accuracy"] == 1.0


def test_refresh_sans_verite_rend_none(spavik, churn):
    """Rien a integrer est un etat normal, pas une exception a attraper."""
    modele = spavik.train(churn, target="churn")
    assert modele.refresh() is None


def test_pagination_transparente(spavik, api, churn):
    for _ in range(7):
        spavik.train(churn, target="churn")
    modeles = list(spavik.models(limit=3))
    assert len(modeles) == 7
    assert len({m.id for m in modeles}) == 7


def test_prevision_et_cout(spavik, api):
    serie = [{"date": f"2026-07-{i+1:02d}", "ventes": 100 + i} for i in range(28)]
    depart = api.solde
    resultat = spavik.forecast(serie, target="ventes", horizon=7)
    assert resultat.cout is None
    assert len(resultat.points) == 7
    assert depart - api.solde == 7


def test_prevision_multi_series(spavik, api):
    serie = [{"boutique": store, "ventes": i} for store in "abcde" for i in range(20)]
    api.solde = 7
    assert api.appels == []
    result = spavik.forecast(serie, target="ventes", horizon=7, item_id="boutique")
    assert result.cout is None
    assert api.solde == 0


@pytest.mark.asyncio
async def test_prevision_multi_series_asynchrone(aspavik, api):
    serie = [{"boutique": store, "ventes": i} for store in "abcde" for i in range(20)]
    api.solde = 7
    assert api.appels == []
    result = await aspavik.forecast(serie, target="ventes", horizon=7, item_id="boutique")
    assert result.cout is None
    assert api.solde == 0


@pytest.mark.asyncio
async def test_asynchrone_donne_le_meme_resultat(aspavik, api, churn):
    modele = await aspavik.train(churn, target="churn")
    assert modele.id.startswith("mdl_")

    prediction = await modele.predict([{"plan": "pro"}])
    assert prediction.cout is None
    assert len(prediction.lignes) == 1

    await modele.submit_outcomes([{"request_id": "req_1", "actual": 1}])
    integration = await modele.refresh()
    assert integration["version"]["version"] == 2

    modeles = [m async for m in aspavik.models()]
    assert len(modeles) == 1
    await aspavik.aclose()


@pytest.mark.asyncio
async def test_asynchrone_refuse_pareil(aspavik, api, churn):
    from spavik import SpavikDataError

    with pytest.raises(SpavikDataError) as exc:
        await aspavik.train(churn[:8], target="churn")
    assert "at least 10 rows" in str(exc.value)
    assert api.appels == []
    await aspavik.aclose()


def test_default_family_is_selected_by_api(spavik, api, churn):
    """The API selects defaults; the client does not resolve or cache them."""
    spavik.train(churn, target="churn")
    assert api.compte("/v1/engines") == 0
    envoye = [a for a in api.appels if a.url.path == "/v1/models" and a.method == "POST"][0]
    import json as _json
    assert "engine_family" not in _json.loads(envoye.content)
    assert "engine" not in _json.loads(envoye.content)

    spavik.train(churn, target="churn")
    assert api.compte("/v1/engines") == 0, "le catalogue ne se relit pas a chaque entrainement"


def test_un_moteur_explicite_court_circuite_la_resolution(spavik, api, churn):
    spavik.train(churn, target="churn", engine_family="presage")
    assert api.compte("/v1/engines") == 0


def test_engines_rend_le_catalogue_tel_que_l_api_le_decrit(spavik, api):
    moteurs = spavik.engines()
    assert [m["id"] for m in moteurs] == ["presage-2"]
    assert moteurs[0]["status"] == "default"


def test_prediction_cost_is_not_invented_from_the_catalogue(spavik, api, churn):
    """A training engine tariff cannot establish the actual debit."""
    import httpx
    api.repondra("/v1/engines", httpx.Response(200, json=[
        {"id": "presage-2", "status": "default", "credits": 1},
        {"id": "big-v1", "status": "preview", "credits": 3}]))
    model = spavik.train(churn, target="churn")
    api.modeles[model.id]["engine"] = "big-v1"   # servi par un moteur a trois credits
    model = spavik.model(model.id)
    assert model.engine == "big-v1"
    assert model.predict([{"plan": "pro"}] * 4).cout is None
    assert api.compte("/v1/engines") == 0, "le catalogue se lit une fois"


def test_usage_rend_le_solde_et_la_periode(spavik, api, churn):
    """Une lecture gratuite du compte, avant de depenser."""
    compte = spavik.usage()
    assert compte["credit_balance"] == 100 and compte["plan"] == "free"
    model = spavik.train(churn, target="churn")
    model.predict([{"plan": "pro"}] * 12)
    compte = spavik.usage()
    assert compte["credit_balance"] == 88 and compte["period"]["units_used"] == 12
    assert api.compte("/v1/usage") == 2


async def test_usage_asynchrone(aspavik, api):
    compte = await aspavik.usage()
    assert compte["credit_balance"] == 100
    await aspavik.aclose()


def test_le_solde_vient_de_l_en_tete_quand_le_corps_ne_l_a_pas(spavik, api):
    """forecast ne rend pas le solde dans son corps : X-Spavik-Predictions-Remaining le donne."""
    serie = [{"date": f"2026-07-{i+1:02d}", "ventes": 100 + i} for i in range(28)]
    r = spavik.forecast(serie, target="ventes", horizon=3)
    assert r.solde == api.solde == 97


def test_archiver_puis_restaurer(spavik, api, churn):
    model = spavik.train(churn, target="churn")
    assert [m.id for m in spavik.models()] == [model.id]
    model.archive()
    assert [m.id for m in spavik.models()] == []
    with pytest.raises(SpavikError) as exc:
        spavik.model(model.id)  # lire un modele archive : refuse, comme la vraie API
    assert exc.value.code == "MODEL_ARCHIVED"
    spavik.restore(model.id)   # sans lecture prealable, donc possible
    assert [m.id for m in spavik.models()] == [model.id]
    chemins = [a.url.path for a in api.appels if a.method == "POST" and "/models/" in a.url.path]
    assert chemins == [f"/v1/models/{model.id}/archive", f"/v1/models/{model.id}/restore"]
    assert not [a for a in api.appels if a.method == "DELETE"], "jamais de suppression"


async def test_archiver_asynchrone(aspavik, api, churn):
    model = await aspavik.train(churn, target="churn")
    await model.archive()
    assert [m async for m in aspavik.models()] == []
    await aspavik.aclose()


def test_evaluer_avant_d_entrainer(spavik, api, churn):
    rapport = spavik.evaluate(churn, target="churn")
    assert api.appels[-1].method == "POST"
    assert api.appels[-1].url.path == "/v1/datasets/evaluate"
    assert rapport["trial"]["verdict"]["level"] == "usable"
    assert rapport["columns"] == ["plan", "seats", "tickets_90d", "churn"] or "plan" in rapport["columns"]
    assert api.solde == 100 and not [m for m in spavik.models()]
    rapport = spavik.evaluate(churn, target="churn_90d")
    assert rapport["trial"] is None and "missing" in rapport["hint"]


def test_backtester_une_serie(spavik, api):
    serie = [{"date": f"2026-07-{i+1:02d}", "ventes": 100 + i} for i in range(28)]
    rapport = spavik.backtest(serie, target="ventes", horizon=7)
    assert rapport["backtest"]["verdict"]["level"] == "usable"
    assert rapport["backtest"]["by_window"] == [0.55, 0.7, 0.61]
    assert api.solde == 100


def test_les_archives_se_listent_a_part(spavik, api, churn):
    model = spavik.train(churn, target="churn")
    model.archive()
    assert [m.id for m in spavik.models()] == []
    assert [m.id for m in spavik.models(status="archived")] == [model.id]


def test_l_historique_des_predictions_porte_les_request_id(spavik, api, churn):
    model = spavik.train(churn, target="churn")
    r = model.predict([{"plan": "pro"}] * 3)
    assert [l["request_id"] for l in r.lignes] == ["req_p0000", "req_p0001", "req_p0002"]
    assert [e["request_id"] for e in model.predictions(limit=2)] == ["req_p0000", "req_p0001"]


async def test_restaurer_asynchrone_par_identifiant(aspavik, api, churn):
    model = await aspavik.train(churn, target="churn")
    await aspavik.archive(model.id)
    await aspavik.restore(model.id)
    assert [m.id async for m in aspavik.models()] == [model.id]
    await aspavik.aclose()


def test_un_horizon_nul_est_refuse_avant_le_backtest(spavik, api):
    """L'API prend un horizon nul pour 1 sans le dire : on refuse avant d'envoyer."""
    from spavik import SpavikDataError
    serie = [{"date": f"2026-07-{i+1:02d}", "ventes": 100 + i} for i in range(28)]
    with pytest.raises(SpavikDataError, match="at least 1"):
        spavik.backtest(serie, target="ventes", horizon=0)
    assert api.compte("/v1/forecast/backtest") == 0


def test_le_modele_dit_les_colonnes_qu_il_attend(spavik, api, churn):
    model = spavik.train(churn, target="churn")
    assert model.features == []
    api.modeles[model.id]["feature_columns"] = ["plan", "seats", "tickets_90d"]
    assert spavik.model(model.id).features == ["plan", "seats", "tickets_90d"]


async def test_evaluer_asynchrone(aspavik, api, churn):
    try:
        rapport = await aspavik.evaluate(churn, target="churn", engine_family="presage")
        assert rapport["trial"]["verdict"]["level"] == "usable"
        requete = api.appels[-1]
        assert requete.method == "POST"
        assert requete.url.path == "/v1/datasets/evaluate"
        import json
        assert json.loads(requete.content) == {
            "data": churn, "target": "churn", "engine_family": "presage",
        }
        assert api.solde == 100 and not api.modeles
    finally:
        await aspavik.aclose()
