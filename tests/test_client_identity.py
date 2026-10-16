"""Client identity and application User-Agent survive retries in both clients."""
import httpx
import pytest
from spavik import Spavik, AsyncSpavik, __version__


def responder(user_agent):
    calls = []
    def reply(request):
        calls.append(request)
        assert request.headers["X-Spavik-Client-Name"] == "spavik-sdk-python"
        assert request.headers["X-Spavik-Client-Version"] == __version__
        assert request.headers["User-Agent"] == (user_agent or f"spavik-python/{__version__}")
        assert request.headers["X-Spavik-Api-Key"] == "fixture-key"
        assert "Authorization" not in request.headers
        assert "X-API-Key" not in request.headers
        return httpx.Response(503, json={"message": "UNAVAILABLE"}) if len(calls) == 1 else httpx.Response(200, json={"plan": "free"})
    return reply, calls


@pytest.mark.parametrize("user_agent", [None, "mon-agent/1.0"])
def test_sync_identity(user_agent):
    reply, calls = responder(user_agent)
    with httpx.Client(transport=httpx.MockTransport(reply)) as transport:
        with Spavik("fixture-key", base_url="https://api.test", user_agent=user_agent,
                    backoff=lambda _: 0, client=transport) as client:
            assert client.usage()["plan"] == "free"
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("user_agent", [None, "mon-agent/1.0"])
async def test_async_identity(user_agent):
    reply, calls = responder(user_agent)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as transport:
        async with AsyncSpavik("fixture-key", base_url="https://api.test", user_agent=user_agent,
                              backoff=lambda _: 0, client=transport) as client:
            assert (await client.usage())["plan"] == "free"
    assert len(calls) == 2
