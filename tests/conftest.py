"""Fixtures partagees par les tests de la bibliotheque."""

from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from api_simulee import CLE, ApiSimulee
from spavik import AsyncSpavik, Spavik

__all__ = ["CLE", "ApiSimulee"]


@pytest.fixture
def api() -> ApiSimulee:
    return ApiSimulee()


@pytest.fixture
def spavik(api: ApiSimulee) -> Spavik:
    transport = httpx.MockTransport(api)
    # La temporisation des reprises est une option du client : les tests
    # l'annulent au lieu de patcher le module.
    return Spavik(CLE, base_url="http://api.test", backoff=lambda _: 0,
                  client=httpx.Client(transport=transport))


@pytest.fixture
def aspavik(api: ApiSimulee) -> AsyncSpavik:
    transport = httpx.MockTransport(api)
    return AsyncSpavik(CLE, base_url="http://api.test", backoff=lambda _: 0,
                       client=httpx.AsyncClient(transport=transport))


@pytest.fixture
def churn() -> List[Dict[str, Any]]:
    """Douze lignes, deux classes : le minimum que l'API accepte, plus deux."""
    return [
        {"plan": "pro",  "seats": 12, "tickets_90d": 3, "churn": 0},
        {"plan": "free", "seats": 1,  "tickets_90d": 9, "churn": 1},
        {"plan": "pro",  "seats": 40, "tickets_90d": 1, "churn": 0},
        {"plan": "free", "seats": 2,  "tickets_90d": 7, "churn": 1},
        {"plan": "team", "seats": 8,  "tickets_90d": 2, "churn": 0},
        {"plan": "free", "seats": 1,  "tickets_90d": 12, "churn": 1},
        {"plan": "pro",  "seats": 25, "tickets_90d": 0, "churn": 0},
        {"plan": "team", "seats": 6,  "tickets_90d": 5, "churn": 1},
        {"plan": "pro",  "seats": 18, "tickets_90d": 1, "churn": 0},
        {"plan": "free", "seats": 3,  "tickets_90d": 8, "churn": 1},
        {"plan": "team", "seats": 11, "tickets_90d": 2, "churn": 0},
        {"plan": "pro",  "seats": 30, "tickets_90d": 4, "churn": 0},
    ]
