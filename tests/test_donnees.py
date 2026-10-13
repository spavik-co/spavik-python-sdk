"""Les formes d'entree acceptees mènent toutes au meme corps de requete."""

from __future__ import annotations

import json

import pytest

from spavik import SpavikDataError
from spavik._data import normaliser


def test_liste_de_dictionnaires(churn):
    assert normaliser(churn) == churn


def test_dictionnaire_seul():
    assert normaliser({"a": 1}) == [{"a": 1}]


def test_csv_brut():
    lignes = normaliser("plan,seats\npro,12\nfree,1\n")
    assert lignes == [{"plan": "pro", "seats": 12}, {"plan": "free", "seats": 1}]


def test_csv_les_nombres_redeviennent_des_nombres():
    lignes = normaliser("a,b,c\n1,2.5,texte\n")
    assert lignes == [{"a": 1, "b": 2.5, "c": "texte"}]


def test_csv_point_virgule():
    assert normaliser("a;b\n1;2\n") == [{"a": 1, "b": 2}]


def test_fichier_csv(tmp_path, churn):
    chemin = tmp_path / "churn.csv"
    entetes = list(churn[0])
    lignes = [",".join(entetes)]
    lignes += [",".join(str(l[c]) for c in entetes) for l in churn]
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    assert normaliser(str(chemin)) == churn


def test_fichier_json(tmp_path, churn):
    chemin = tmp_path / "churn.json"
    chemin.write_text(json.dumps(churn), encoding="utf-8")
    assert normaliser(str(chemin)) == churn


def test_fichier_absent_dit_le_chemin():
    with pytest.raises(SpavikDataError) as exc:
        normaliser("/chemin/qui/nexiste/pas.csv")
    assert "file not found" in str(exc.value)
    assert "/chemin/qui/nexiste/pas.csv" in str(exc.value)


def test_liste_vide_refusee():
    with pytest.raises(SpavikDataError):
        normaliser([])


def test_type_non_pris_en_charge():
    with pytest.raises(SpavikDataError) as exc:
        normaliser(42)
    assert "int" in str(exc.value)


def test_dataframe_si_pandas_est_la(churn):
    pandas = pytest.importorskip("pandas")
    df = pandas.DataFrame(churn)
    assert normaliser(df) == churn


def test_dataframe_nan_devient_none():
    pandas = pytest.importorskip("pandas")
    df = pandas.DataFrame([{"a": 1.0}, {"a": None}])
    assert normaliser(df) == [{"a": 1.0}, {"a": None}]
