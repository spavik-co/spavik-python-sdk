"""Integration contract: API owns defaults, diagnostics, IDs and retry decisions."""
import inspect
import json
import httpx
import pytest
from spavik import Spavik, AsyncSpavik, SpavikError
from spavik._retry import retry_delay

ROWS = [{"x": i, "y": i % 2} for i in range(12)]
CALIBRATION = {"available": False, "unavailable_reason": "missing_probabilities",
    "evaluated_count": 12, "evaluated_on": "test", "kind": "one_vs_rest",
    "interpretation": "descriptive_only", "binning": "uniform", "n_bins": 10,
    "bin_boundaries": "left_closed_right_open_last_closed", "per_class": []}
POINTS = [{"series": "a", "window": 0, "timestamp": "2026-10-01", "actual": 3,
    "prediction": 2, "naive_prediction": 1, "constant_prediction": 1, "quantiles": {"0.5": 2}}]

async def resolve(value):
    return await value if inspect.isawaitable(value) else value

@pytest.mark.parametrize("asynchronous", [False, True])
async def test_wire_contract_and_diagnostics(asynchronous):
    calls = []
    def handle(request):
        calls.append(request)
        body = json.loads(request.content) if request.content else {}
        assert "engine" not in body
        headers = {"X-Spavik-Request-Id": "req_http_current", "X-Request-Id": "obsolete",
                   "X-Spavik-Model-Version": "presage-2", "X-Spavik-Predictions-Remaining": "80"}
        path = request.url.path
        if path == "/v1/engine-families":
            result = [{"id": "presage", "label": "Presage", "is_default": True}]
        elif path == "/v1/models":
            result = {"model": {"id": "mdl_test", "engine_family": "presage", "latest_version": 7},
                      "version": {"version": 7, "engine": "presage-2", "calibration": CALIBRATION}}
        elif path.endswith("/predict"):
            result = {"version": 7, "engine": "presage-2", "_request_id": "stale_replay",
                      "predictions": [{"prediction": 1, "request_id": "req_prediction_original"}]}
        elif path.endswith("evaluate"):
            result = {"trial": {"calibration": CALIBRATION}}
        elif path.endswith("performance"):
            result = {"observed": None, "training_calibration": CALIBRATION}
        else:
            result = {"engine": "presage-2", "backtest": {"predictions": POINTS}, "forecast_csv": "y_prediction\n2"}
        return httpx.Response(200, json=result, headers=headers)
    transport = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=httpx.MockTransport(handle))
    client = (AsyncSpavik if asynchronous else Spavik)("fixture", client=transport)
    try:
        model = await resolve(client.train(ROWS, target="y"))
        assert json.loads(calls[-1].content) == {"data": ROWS, "target": "y"}
        assert len(calls) == 1  # no catalogue lookup or local default
        assert model.engine_family == "presage" and model.version == 7
        assert model.training["calibration"] == CALIBRATION
        await resolve(client.train(ROWS, target="y", engine_family="presage"))
        assert json.loads(calls[-1].content)["engine_family"] == "presage"
        result = await resolve(model.predict([{"x": 1}], engine_version="presage-latest"))
        assert json.loads(calls[-1].content) == {"rows": [{"x": 1}], "engine_version": "presage-latest"}
        assert result.version == 7 and result.engine == "presage-2"
        assert result.request_id == "req_http_current" and result.lignes[0]["request_id"] == "req_prediction_original"
        assert result.cout is None and result.solde == 80
        for method in ["forecast", "backtest"]:
            options = dict(target="y", horizon=2, engine_family="presage", engine_version="presage-2", include_backtest_predictions=True)
            if method == "forecast": options["backtest"] = True
            result = await resolve(getattr(client, method)(ROWS, **options))
            sent = json.loads(calls[-1].content)
            assert sent == {"data": ROWS, **options}
            data = result.donnees if method == "forecast" else result
            assert data["backtest"]["predictions"] == POINTS
        report = await resolve(client.evaluate(ROWS, target="y", engine_family="presage"))
        assert report["trial"]["calibration"] == CALIBRATION
        report = await resolve(model.performance())
        assert report["training_calibration"] == CALIBRATION
        assert (await resolve(client.engine_families()))[0]["is_default"] is True
    finally:
        await resolve(transport.aclose() if asynchronous else transport.close())

@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("code", ["REQUEST_INTERRUPTED", "IDEMPOTENCY_RESPONSE_UNAVAILABLE"])
@pytest.mark.parametrize("operation", ["train", "refresh"])
async def test_uncertain_mutation_is_not_retried_or_swallowed(asynchronous, code, operation):
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == "GET": return httpx.Response(200, json={"id": "mdl_test"})
        return httpx.Response(503, json={"message": code}, headers={"X-Spavik-Request-Id": "req_uncertain", "Retry-After": "0"})
    transport = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=httpx.MockTransport(handle))
    client = (AsyncSpavik if asynchronous else Spavik)("fixture", client=transport)
    try:
        model = await resolve(client.model("mdl_test")) if operation == "refresh" else None
        with pytest.raises(SpavikError) as error:
            await resolve(model.refresh() if model else client.train(ROWS, target="y"))
        assert error.value.code == code and error.value.request_id == "req_uncertain"
        posts = [c for c in calls if c.method == "POST"]
        assert len(posts) == 1 and error.value.idempotency_key == posts[0].headers["Idempotency-Key"]
    finally:
        await resolve(transport.aclose() if asynchronous else transport.close())

@pytest.mark.parametrize("asynchronous", [False, True])
async def test_retry_after_and_original_key(asynchronous, monkeypatch):
    calls, waits = [], []
    monkeypatch.setattr("spavik.client.time.sleep", waits.append)
    async def sleep(seconds): waits.append(seconds)
    monkeypatch.setattr("spavik.client.asyncio.sleep", sleep)
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(409, json={"message": "REQUEST_IN_PROGRESS"}, headers={"Retry-After": "2"})
        return httpx.Response(201, json={"model": {"id": "mdl_test"}})
    transport = (httpx.AsyncClient if asynchronous else httpx.Client)(transport=httpx.MockTransport(handle))
    client = (AsyncSpavik if asynchronous else Spavik)("fixture", client=transport)
    try:
        await resolve(client.train(ROWS, target="y"))
        assert waits == [2] and len(calls) == 2
        assert calls[0].content == calls[1].content
        assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]
    finally:
        await resolve(transport.aclose() if asynchronous else transport.close())


def test_retry_delay_contract():
    assert retry_delay(None, "ENGINE_BUSY", 0) == 5
    assert retry_delay("7", "ENGINE_BUSY", 0) == 7
    assert retry_delay("0", "ENGINE_BUSY", 0) == 0
    assert retry_delay("garbage", "ENGINE_BUSY", 0) == 5
    assert retry_delay("nan", "ENGINE_BUSY", 0) == 5
