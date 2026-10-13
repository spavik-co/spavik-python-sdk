"""Les credentials sont transmis ; seule l'API les accepte ou les refuse."""
import httpx
import pytest

from spavik import Spavik, AsyncSpavik, SpavikAuthError


@pytest.mark.parametrize("key", ["", "sk-spv-admin-fixture", "opaque-token"])
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
    assert calls[0].headers.get("X-API-Key") == (key if key else None)
    assert "Authorization" not in calls[0].headers


@pytest.mark.parametrize("key", ["", "sk-spv-admin-fixture", "opaque-token"])
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
    assert calls[0].headers.get("X-API-Key") == (key if key else None)
    assert "Authorization" not in calls[0].headers


def test_omitted_key_reads_environment(monkeypatch):
    monkeypatch.setenv("SPAVIK_API_KEY", "configured-key")
    with Spavik() as client:
        assert client.cle_api == "configured-key"
    monkeypatch.delenv("SPAVIK_API_KEY")
    with Spavik() as client:
        assert client.cle_api == ""
