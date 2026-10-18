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


def test_pathlike_est_un_chemin_meme_sans_extension(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    Path("dataset").write_text("x,target\n1,0\n", encoding="utf-8")
    assert normaliser(Path("dataset")) == [{"x": 1, "target": 0}]
    with pytest.raises(SpavikDataError, match="file not found"):
        normaliser(Path("missing"))


def test_pathlike_json_commencant_par_crochet(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    path = Path("[dataset].json")
    path.write_text('[{"url":"https://example.invalid","target":0}]', encoding="utf-8")
    assert normaliser(path) == [{"url": "https://example.invalid", "target": 0}]


@pytest.mark.parametrize("content", ['[{"x":', '\ufeff[{"x":'])
def test_json_invalide_est_une_erreur_de_donnees(content):
    with pytest.raises(SpavikDataError, match="invalid JSON at line"):
        normaliser(content)


def test_json_brut_avec_bom():
    assert normaliser('\ufeff [{"url":"https://example.invalid"}]') == [
        {"url": "https://example.invalid"}]


def test_csv_fichier_invalide_indique_la_ligne(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("x,target\n1,0\n2,1,LOST\n", encoding="utf-8")
    with pytest.raises(SpavikDataError, match="bad.csv: CSV line 3"):
        normaliser(path)


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
