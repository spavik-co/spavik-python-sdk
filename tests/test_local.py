"""Ce qui est refuse sans toucher au reseau.

Chaque test verifie deux choses : le refus, et le fait qu'aucune requete n'est
partie. Un controle local qui appelle quand meme ne sert a rien.
"""

from __future__ import annotations

import pytest

from spavik import SpavikDataError


def test_moins_de_dix_lignes_refuse_sans_appel(spavik, api, churn):
    with pytest.raises(SpavikDataError) as exc:
        spavik.train(churn[:8], target="churn")
    assert "at least 10 rows" in str(exc.value)
    assert "8 provided" in str(exc.value)
    assert api.appels == []


def test_colonne_cible_absente_suggere_la_proche(spavik, api, churn):
    with pytest.raises(SpavikDataError) as exc:
        spavik.train(churn, target="churn_90d")
    message = str(exc.value)
    assert "'churn_90d' is missing" in message
    assert "Did you mean 'churn'" in message
    assert "plan, seats, tickets_90d, churn" in message
    assert api.appels == []


def test_cible_constante_refusee(spavik, api, churn):
    plates = [dict(ligne, churn=0) for ligne in churn]
    with pytest.raises(SpavikDataError) as exc:
        spavik.train(plates, target="churn")
    assert "a single value" in str(exc.value)
    assert api.appels == []


def test_serie_plus_courte_que_son_horizon(spavik, api):
    serie = [{"date": f"2026-07-0{i+1}", "ventes": 100 + i} for i in range(3)]
    with pytest.raises(SpavikDataError) as exc:
        spavik.forecast(serie, target="ventes", horizon=14)
    assert "3 point(s) for a horizon of 14" in str(exc.value)
    assert api.appels == []


def test_horizon_nul_refuse(spavik, api):
    serie = [{"ventes": 1} for _ in range(30)]
    with pytest.raises(SpavikDataError):
        spavik.forecast(serie, target="ventes", horizon=0)
    assert api.appels == []


def test_aucune_ligne_a_scorer(spavik, api, churn):
    modele = spavik.train(churn, target="churn")
    api.appels.clear()
    with pytest.raises(SpavikDataError):
        modele.predict([])
    assert api.appels == []


def test_un_refus_local_ne_va_pas_chercher_le_moteur(spavik, api, churn):
    """Le client resout le moteur par defaut, mais jamais avant de valider.

    Sans cette garantie, un fichier trop court declencherait quand meme un
    aller-retour, et le refus ne serait plus vraiment local.
    """
    with pytest.raises(SpavikDataError):
        spavik.train(churn[:8], target="churn")
    assert api.appels == []
    assert api.compte("/v1/engines") == 0


def test_verite_sans_valeur_observee(spavik, api, churn):
    modele = spavik.train(churn, target="churn")
    api.appels.clear()
    with pytest.raises(SpavikDataError) as exc:
        modele.submit_outcomes([{"request_id": "req_1", "outcome": 1}])
    message = str(exc.value)
    assert "'actual'" in message, "the expected field must be named"
    assert "request_id, outcome" in message, "the fields found must be listed"
    assert api.appels == []


def test_verite_sans_rattachement(spavik, api, churn):
    modele = spavik.train(churn, target="churn")
    api.appels.clear()
    with pytest.raises(SpavikDataError) as exc:
        modele.submit_outcomes([{"actual": 1}])
    assert "which prediction" in str(exc.value)
    assert api.appels == []
