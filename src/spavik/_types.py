"""Formes des rapports rendus par l'API, pour l'IDE et les verificateurs de types.

Ce sont des dictionnaires ordinaires a l'execution : la bibliotheque transmet
le rapport de l'API tel quel, sans recalcul. `total=False` parce que l'API
peut ajouter ou omettre des champs selon le cas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class EvaluationReport(TypedDict, total=False):
    """What `evaluate()` returns: the API report, unchanged.

    `validation` lists what would block training, `hint` says what to fix
    first, `trial` holds the trial run (None when validation failed), and
    `assessment` gives `status`, `metric` and a plain `message`.
    """

    target: str
    task: Optional[str]
    n_rows: int
    columns: List[str]
    validation: Dict[str, Any]
    assessment: Optional[Dict[str, Any]]
    hint: Optional[str]
    trial: Optional[Dict[str, Any]]


class BacktestReport(TypedDict, total=False):
    """What `backtest()` returns: the API report, unchanged.

    `validation` checks length, step and duplicates, `backtest` replays past
    windows against simple references, and `assessment` gives `status`,
    `metric` and a plain `message`.
    """

    target: str
    timestamp: Optional[str]
    item_id: Optional[str]
    n_rows: int
    columns: List[str]
    validation: Dict[str, Any]
    assessment: Optional[Dict[str, Any]]
    hint: Optional[str]
    backtest: Optional[Dict[str, Any]]


class Usage(TypedDict, total=False):
    """What `usage()` returns: the account as the API sees it."""

    plan: str
    credit_balance: int
    credits_low: bool
    predictions_remaining: Optional[int]
    unlimited_usage: bool
    included_units_per_month: Optional[int]
    period: Dict[str, Any]
    window: Dict[str, Any]
    totals: Dict[str, Any]
    daily: List[Dict[str, Any]]
    by_kind: List[Dict[str, Any]]
    by_workspace: List[Dict[str, Any]]
    by_api_key: List[Dict[str, Any]]
