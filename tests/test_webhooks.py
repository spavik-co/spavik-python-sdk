"""Verification de signature des webhooks, au format emis par l'API."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from spavik.webhooks import SpavikSignatureError, verifier

SECRET = "whsec_de_test"


def signer(corps: bytes, horodatage: int | None = None, secret: str = SECRET) -> dict:
    """Reproduit signPayload de l'API : HMAC de `<t>.` + octets bruts."""
    t = int(time.time()) if horodatage is None else horodatage
    signature = hmac.new(secret.encode(), f"{t}.".encode() + corps, hashlib.sha256).hexdigest()
    return {"Spavik-Signature": f"t={t},v1={signature}"}


EVENEMENT = {
    "id": "evt_1",
    "type": "model.trained",
    "created_at": "2026-10-11T12:00:00.000Z",
    "workspace_id": "ws_1",
    "data": {"model_id": "mdl_1"},
}


def test_signature_valide_rend_l_evenement():
    corps = json.dumps(EVENEMENT).encode()
    evenement = verifier(corps, signer(corps), SECRET)
    assert evenement["type"] == "model.trained"
    assert evenement["id"] == "evt_1"


def test_corps_texte_accepte():
    corps = json.dumps(EVENEMENT)
    assert verifier(corps, signer(corps.encode()), SECRET)["type"] == "model.trained"


def test_nom_d_entete_insensible_a_la_casse():
    corps = b'{"type":"credits.low"}'
    entetes = {"spavik-signature": signer(corps)["Spavik-Signature"]}
    assert verifier(corps, entetes, SECRET)["type"] == "credits.low"


def test_signature_invalide():
    corps = b'{"type":"model.trained"}'
    entetes = {"Spavik-Signature": f"t={int(time.time())},v1={'0' * 64}"}
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(corps, entetes, SECRET)
    assert "invalid signature" in str(exc.value)


def test_mauvais_secret():
    corps = b'{"type":"model.trained"}'
    with pytest.raises(SpavikSignatureError):
        verifier(corps, signer(corps), "un-autre-secret")


def test_corps_modifie_apres_signature():
    corps = b'{"type":"model.trained","credits":10}'
    entetes = signer(corps)
    with pytest.raises(SpavikSignatureError):
        verifier(b'{"type":"model.trained","credits":9999}', entetes, SECRET)


def test_horodatage_signe_avec_le_corps():
    corps = b'{"type":"model.trained"}'
    t = int(time.time())
    signature = signer(corps, t)["Spavik-Signature"].split(",v1=")[1]
    with pytest.raises(SpavikSignatureError):
        verifier(corps, {"Spavik-Signature": f"t={t - 1},v1={signature}"}, SECRET)


def test_rejeu_hors_tolerance():
    corps = b'{"type":"model.trained"}'
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(corps, signer(corps, int(time.time()) - 3600), SECRET)
    assert "Likely a replay" in str(exc.value)


def test_horodatage_obligatoire():
    corps = b'{"type":"model.trained"}'
    signature = hmac.new(SECRET.encode(), corps, hashlib.sha256).hexdigest()
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(corps, {"Spavik-Signature": f"v1={signature}"}, SECRET)
    assert "unreadable Spavik-Signature" in str(exc.value)


def test_ancien_entete_refuse():
    corps = b'{"type":"model.trained"}'
    signature = hmac.new(SECRET.encode(), corps, hashlib.sha256).hexdigest()
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(corps, {"X-Spavik-Signature": signature}, SECRET)
    assert "no Spavik-Signature header" in str(exc.value)


def test_entete_de_signature_absent():
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(b"{}", {}, SECRET)
    assert "no Spavik-Signature header" in str(exc.value)


def test_une_des_signatures_v1_suffit():
    corps = b'{"type":"model.trained"}'
    t = int(time.time())
    bonne = signer(corps, t)["Spavik-Signature"].split(",v1=")[1]
    entetes = {"Spavik-Signature": f"t={t},v1={'0' * 64},v1={bonne}"}
    assert verifier(corps, entetes, SECRET)["type"] == "model.trained"
