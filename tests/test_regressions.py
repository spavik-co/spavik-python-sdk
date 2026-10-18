"""Consumer regressions for both clients, observed at the HTTP boundary."""

import inspect
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from spavik import AsyncSpavik, Spavik, SpavikDataError, SpavikTransportError


ROWS = [{"x": i, "target": i % 2} for i in range(12)]


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def asynchronous(request):
    return request.param


async def resolve(result):
    return await result if inspect.isawaitable(result) else result


@asynccontextmanager
async def client_for(asynchronous, handler, **options):
    options = {"api_key": "fixture-key", "base_url": "https://fixture.invalid",
               "backoff": lambda _: 0, **options}
    if asynchronous:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            async with AsyncSpavik(client=transport, **options) as client:
                yield client
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            with Spavik(client=transport, **options) as client:
                yield client


@pytest.mark.parametrize("options,usage_timeout,train_timeout", [
    ({}, 15.0, 120.0),
    ({"timeout": None}, 15.0, 120.0),
    ({"timeout": 0.25}, 0.25, 0.25),
    ({"timeout": 30.0}, 30.0, 30.0),
    ({"timeout": 0.0}, 0.0, 0.0),
])
async def test_timeout_precedence(asynchronous, options, usage_timeout, train_timeout):
    observed = []

    def handler(request):
        observed.append(request.extensions["timeout"])
        return httpx.Response(200, json={"model": {"id": "mdl_fixture"}})

    async with client_for(asynchronous, handler, **options) as client:
        await resolve(client.usage())
        await resolve(client.train(ROWS, target="target"))
    assert observed == [dict.fromkeys(("connect", "read", "write", "pool"), t)
                        for t in (usage_timeout, train_timeout)]


@pytest.mark.parametrize("mutation", [False, True], ids=["read", "mutation"])
async def test_network_failure_keeps_request_identity(asynchronous, mutation):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("Response lost after sending", request=request)

    async with client_for(asynchronous, handler, timeout=0.25, max_retries=3) as client:
        with pytest.raises(SpavikTransportError) as caught:
            await resolve(client.train(ROWS, target="target") if mutation else client.usage())
    assert len(requests) == 3
    keys = [r.headers.get("Idempotency-Key") for r in requests]
    assert len(set(keys)) == 1
    assert bool(keys[0]) is mutation
    assert caught.value.idempotency_key == keys[0]
    assert isinstance(caught.value.__cause__, httpx.ReadTimeout)
    assert all(r.extensions["timeout"]["read"] == 0.25 for r in requests)
    assert len({r.content for r in requests}) == 1


@pytest.mark.parametrize("as_array", [False, True], ids=["object", "array"])
async def test_json_content_with_paths_reaches_api(asynchronous, as_array):
    row = {"url": "https://example.invalid/product", "path": "/data/example.csv", "target": 0}
    content = json.dumps([row] if as_array else row)
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["data"])
        return httpx.Response(200, json={})

    async with client_for(asynchronous, handler) as client:
        await resolve(client.evaluate(content, target="target"))
    assert sent == [[row]]


@pytest.mark.parametrize("content,line", [
    ("x,target\n1,0,LOST\n2,1,LOST\n", 2),
    ("x,target\n1,0\n2,1,LOST\n", 3),
    ("x,x,target\n1,2,0\n", 1),
    ("x,,target\n1,2,0\n", 1),
    ("x,   ,target\n1,2,0\n", 1),
    ('x,target\n"unterminated,0\n', 2),
])
async def test_malformed_csv_is_rejected_before_http(asynchronous, content, line):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with client_for(asynchronous, handler) as client:
        with pytest.raises(SpavikDataError, match=f"CSV line {line}"):
            await resolve(client.evaluate(content, target="target"))
    assert calls == []


@pytest.mark.parametrize("content,expected", [
    ('x,target\n"a,b",0\n"c\nd",1\n', [{"x": "a,b", "target": 0}, {"x": "c\nd", "target": 1}]),
    ("x,target\n1,0\n2\n", [{"x": 1, "target": 0}, {"x": 2, "target": None}]),
])
async def test_valid_csv_preserves_quoted_and_missing_values(asynchronous, content, expected):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["data"])
        return httpx.Response(200, json={})

    async with client_for(asynchronous, handler) as client:
        await resolve(client.evaluate(content, target="target"))
    assert sent == [expected]
