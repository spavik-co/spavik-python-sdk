"""Verification de signature des webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from spavik.webhooks import SpavikSignatureError, verifier

SECRET = "whsec_de_test"


def signer(corps: bytes, horodatage: int | None = None) -> dict:
    if horodatage is None:
        charge, entetes = corps, {}
    else:
        charge = f"{horodatage}.".encode() + corps
        entetes = {"X-Spavik-Timestamp": str(horodatage)}
    signature = hmac.new(SECRET.encode(), charge, hashlib.sha256).hexdigest()
    return {**entetes, "X-Spavik-Signature": signature}


def test_signature_valide_rend_l_evenement():
    corps = json.dumps({"event": "model.trained", "model_id": "mdl_1"}).encode()
    evenement = verifier(corps, signer(corps, int(time.time())), SECRET)
    assert evenement["event"] == "model.trained"


def test_sans_horodatage():
    corps = b'{"event":"credits.low"}'
    assert verifier(corps, signer(corps), SECRET)["event"] == "credits.low"


def test_signature_invalide():
    corps = b'{"event":"model.trained"}'
    entetes = signer(corps, int(time.time()))
    entetes["X-Spavik-Signature"] = "0" * 64
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(corps, entetes, SECRET)
    assert "invalid signature" in str(exc.value)


def test_mauvais_secret():
    corps = b'{"event":"model.trained"}'
    with pytest.raises(SpavikSignatureError):
        verifier(corps, signer(corps, int(time.time())), "un-autre-secret")


def test_corps_modifie_apres_signature():
    corps = b'{"event":"model.trained","credits":10}'
    entetes = signer(corps, int(time.time()))
    with pytest.raises(SpavikSignatureError):
        verifier(b'{"event":"model.trained","credits":9999}', entetes, SECRET)


def test_rejeu_hors_tolerance():
    corps = b'{"event":"model.trained"}'
    vieux = int(time.time()) - 3600
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(corps, signer(corps, vieux), SECRET)
    assert "Likely a replay" in str(exc.value)


def test_entete_de_signature_absent():
    with pytest.raises(SpavikSignatureError) as exc:
        verifier(b"{}", {}, SECRET)
    assert "no signature header" in str(exc.value)


def test_prefixe_toleré():
    corps = b'{"event":"model.trained"}'
    entetes = signer(corps, int(time.time()))
    entetes["X-Spavik-Signature"] = "sha256=" + entetes["X-Spavik-Signature"]
    assert verifier(corps, entetes, SECRET)["event"] == "model.trained"
