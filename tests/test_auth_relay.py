"""Les credentials sont transmis ; seule l'API les accepte ou les refuse."""
import httpx
import pytest

from spavik import Spavik, AsyncSpavik, SpavikAuthError


@pytest.mark.parametrize("key", ["sk-spv-admin-fixture", "opaque-token"])
@pytest.mark.parametrize("status", [200, 401, 403])
def test_credentials_are_decided_by_api(monkeypatch, key, status):
    monkeypatch.setenv("SPAVIK_API_KEY", "environment-must-not-leak")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"plan": "free"} if status == 200 else {
            "message": "API_KEY_INVALID", "messageDetail": "Refused by API",
        })
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        client = Spavik(key, client=transport)
        if status == 200:
            assert client.usage()["plan"] == "free"
        else:
            with pytest.raises(SpavikAuthError):
                client.usage()
    assert len(calls) == 1
    assert calls[0].headers.get("Authorization") == f"Bearer {key}"
    assert "X-Spavik-Api-Key" not in calls[0].headers


@pytest.mark.parametrize("key", ["sk-spv-admin-fixture", "opaque-token"])
async def test_async_credentials_reach_api(monkeypatch, key):
    monkeypatch.setenv("SPAVIK_API_KEY", "environment-must-not-leak")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(401, json={"message": "API_KEY_INVALID"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        client = AsyncSpavik(key, client=transport)
        with pytest.raises(SpavikAuthError):
            await client.usage()
    assert len(calls) == 1
    assert calls[0].headers.get("Authorization") == f"Bearer {key}"
    assert "X-Spavik-Api-Key" not in calls[0].headers


def test_omitted_key_reads_environment(monkeypatch):
    monkeypatch.setenv("SPAVIK_API_KEY", "configured-key")
    with Spavik() as client:
        assert client.cle_api == "configured-key"
    monkeypatch.delenv("SPAVIK_API_KEY")
    with Spavik() as client:
        assert client.cle_api == ""


def test_supplied_client_authorization_is_replaced_by_the_key():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"plan": "free"})
    transport = httpx.Client(transport=httpx.MockTransport(handle),
                             headers={"Authorization": "Bearer sk-spv-api-other"})
    with transport, Spavik("sk-spv-api-fixture", client=transport) as client:
        client.usage()
    assert calls[0].headers.get_list("Authorization") == ["Bearer sk-spv-api-fixture"]
    assert "X-Spavik-Api-Key" not in calls[0].headers


@pytest.mark.parametrize("asynchrone", [False, True])
async def test_two_different_keys_surface_api_key_conflict(asynchrone):
    calls = []
    def handle(request):
        calls.append(request)
        cle = request.headers.get("X-Spavik-Api-Key")
        if cle is not None and request.headers["Authorization"] != f"Bearer {cle}":
            return httpx.Response(400, json={
                "message": "API_KEY_CONFLICT",
                "messageDetail": "Two different API keys were sent (Authorization and X-Spavik-Api-Key). Send a single key.",
            })
        return httpx.Response(200, json={"plan": "free"})
    entetes = {"X-Spavik-Api-Key": "sk-spv-api-other"}
    if asynchrone:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), headers=entetes) as transport:
            with pytest.raises(SpavikAuthError) as exc:
                await AsyncSpavik("sk-spv-api-fixture", client=transport).usage()
    else:
        with httpx.Client(transport=httpx.MockTransport(handle), headers=entetes) as transport:
            with pytest.raises(SpavikAuthError) as exc:
                Spavik("sk-spv-api-fixture", client=transport).usage()
    assert exc.value.code == "API_KEY_CONFLICT" and exc.value.status == 400
    assert len(calls) == 1
