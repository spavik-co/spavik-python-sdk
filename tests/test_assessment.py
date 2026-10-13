"""Les reponses REST sont conservees integralement, en synchrone et asynchrone."""
import httpx
import pytest
from spavik import Spavik, AsyncSpavik

STATUSES = ["better_than_baseline", "not_better_than_baseline", "inconclusive", "not_evaluated", None]

@pytest.mark.parametrize("method", ["evaluate", "backtest"])
@pytest.mark.parametrize("status", STATUSES)
async def test_rest_assessment_is_preserved(method, status):
    payload = {"validation": {"status": "passed"}, "trial": None}
    if status is not None:
        payload["assessment"] = {"status": status, "metric": "AUC" if method == "evaluate" else "MASE", "message": "Exact API message"}
    def handle(request):
        expected = "/v1/datasets/evaluate" if method == "evaluate" else "/v1/forecast/backtest"
        assert request.url.path == expected
        return httpx.Response(200, json=payload)
    data = [{"x": 1, "y": 2}]
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        result = getattr(Spavik("", client=transport), method)(data, target="y")
        assert result == {**payload, "_request_id": None}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        result = await getattr(AsyncSpavik("", client=transport), method)(data, target="y")
        assert result == {**payload, "_request_id": None}
