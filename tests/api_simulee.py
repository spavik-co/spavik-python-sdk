"""Une API simulee, suffisamment fidele pour eprouver le transport.

Elle compte les appels, honore la cle d'idempotence, debite un credit par ligne
scoree, et sait rendre du HTML sur une route inconnue, comme le fait la vraie.
"""

from __future__ import annotations

import json
from typing import Optional, Any, Dict, List

import httpx

CLE = "sk-spv-api-TEST-FIXTURE-not-a-real-key"


class ApiSimulee:
    def __init__(self) -> None:
        self.appels: List[httpx.Request] = []
        self.solde = 100
        self.idempotence: Dict[str, Any] = {}
        self.scenario: Dict[str, List[Any]] = {}
        self.modeles: Dict[str, Dict[str, Any]] = {}
        self.pending_outcomes = 0
        self._compteur = 0
        self._scores = 0

    # -- pilotage ---------------------------------------------------------
    def repondra(self, chemin: str, *reponses: Any) -> None:
        """Empile des reponses pour un chemin, consommees dans l'ordre."""
        self.scenario.setdefault(chemin, []).extend(reponses)

    def compte(self, chemin: str) -> int:
        return sum(1 for a in self.appels if a.url.path == chemin)

    # -- serveur ----------------------------------------------------------
    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.appels.append(requete)
        chemin = requete.url.path

        presentee = requete.headers.get("X-API-Key")
        if presentee != CLE:
            return self._json(401, {"status": "error", "message": "API_KEY_INVALID",
                                    "messageDetail": "API key is invalid or revoked."})

        empile = self.scenario.get(chemin)
        if empile:
            reponse = empile.pop(0)
            if isinstance(reponse, Exception):
                raise reponse
            return reponse

        cle_idem = requete.headers.get("Idempotency-Key")
        if cle_idem and cle_idem in self.idempotence:
            return self._json(200, self.idempotence[cle_idem])

        reponse = self._router(requete, chemin)
        if cle_idem and reponse.status_code < 400:
            self.idempotence[cle_idem] = json.loads(reponse.text)
        return reponse

    def _router(self, requete: httpx.Request, chemin: str) -> httpx.Response:
        corps = json.loads(requete.content) if requete.content else {}

        if chemin == "/v1/usage":
            # La forme observee sur la passerelle de test le 11 septembre 2026.
            return self._json(200, {
                "plan": "free", "credit_balance": self.solde, "credits_low": self.solde < 10,
                "included_units_per_month": None,
                "period": {"key": "2026-09", "reset_at": "2026-10-01T00:00:00.000Z",
                           "units_used": 100 - self.solde},
                "totals": {"units": 100 - self.solde},
                "by_kind": [{"key": "predict", "label": None, "units": 100 - self.solde}]})

        if chemin == "/v1/datasets/evaluate":
            lignes = corps.get("data") or []
            cible = corps.get("target")
            colonnes = list(lignes[0]) if lignes else []
            if cible not in colonnes:
                return self._json(200, {
                    "target": cible, "task": None, "n_rows": len(lignes), "columns": colonnes,
                    "validation": {"status": "failed", "issues": [{"code": "TARGET_COLUMN_MISSING"}]},
                    "hint": f"The target column '{cible}' is missing. Columns: {colonnes}",
                    "trial": None})
            return self._json(200, {
                "target": cible, "task": "classification", "n_rows": len(lignes),
                "columns": colonnes, "validation": {"status": "ok", "issues": []}, "hint": None,
                "trial": {"metrics": {"accuracy": 0.83}, "baselines": {"majority_accuracy": 0.5},
                          "verdict": {"level": "usable",
                                      "message": "The engine beats the majority class on this data."}}})

        if chemin == "/v1/forecast/backtest":
            lignes = corps.get("data") or []
            cible = corps.get("target")
            return self._json(200, {
                "target": cible, "timestamp": corps.get("timestamp") or "date",
                "item_id": corps.get("item_id"), "n_rows": len(lignes),
                "columns": list(lignes[0]) if lignes else [],
                "validation": {"status": "ok", "issues": []}, "hint": None,
                "backtest": {"metrics": {"MASE": 0.62}, "baselines": {"naive_mase": 1.0},
                             "by_window": [0.55, 0.7, 0.61], "seasonal_period": 7,
                             "warnings": None, "n_context": len(lignes),
                             "verdict": {"level": "usable",
                                         "message": "The engine beats the naive forecast on this series."}}})

        if chemin == "/v1/engines":
            return self._json(200, [{"id": "tabicl-v2", "label": "TabICL v2",
                                     "status": "default", "credits": 1, "min_plan": None,
                                     "retires_at": None}])

        if chemin == "/v1/models" and requete.method == "POST":
            if not corps.get("engine"):
                # L'API refuse un entrainement sans moteur, meme si le contrat
                # ne le compte pas parmi les champs requis.
                return self._json(422, {"status": "error", "message": "ENGINE_REQUIRED",
                                        "messageDetail": "Declare the engine to train with (engine)."})
            if corps["engine"] != "tabicl-v2":
                # Un moteur hors catalogue : l'API le refuse par son code.
                return self._json(422, {"status": "error", "message": "ENGINE_UNKNOWN",
                                        "messageDetail": f"Unknown engine '{corps['engine']}'."})
            self._compteur += 1
            mid = f"mdl_test{self._compteur:04d}"
            self.modeles[mid] = {"id": mid, "name": corps.get("name") or "modele",
                                 "latest_version": 1, "task": "classification"}
            return self._json(201, {"model": self.modeles[mid],
                                    "version": {"version": 1, "id": "ver_1"},
                                    "validation": {"row_count": len(corps.get("data") or [])},
                                    "credits_remaining": self.solde})

        if chemin == "/v1/models" and requete.method == "GET":
            limite = int(requete.url.params.get("limit", 50))
            decalage = int(requete.url.params.get("offset", 0))
            voulu = requete.url.params.get("status")
            tous = [m for m in self.modeles.values()
                    if (m.get("status") == "archived") == (voulu == "archived")]
            page = tous[decalage:decalage + limite]
            return self._json(200, {"data": page, "pagination": {"total": len(tous),
                                                                 "limit": limite,
                                                                 "offset": decalage}})

        if chemin.endswith("/predict"):
            lignes = corps.get("rows") or []
            cout = len(lignes)
            if cout > self.solde:
                return self._json(402, {"status": "error", "message": "CREDITS_EXHAUSTED",
                                        "messageDetail": "Not enough credits.",
                                        "balance": self.solde, "required": cout})
            self.solde -= cout
            self._scores += cout
            return self._json(200, {
                "model_id": chemin.split("/")[3], "version": 1, "n_scored": cout,
                "predictions": [{"request_id": f"req_p{self._scores - cout + i:04d}", "prediction": 1,
                                 "proba_0": 0.2, "proba_1": 0.8} for i in range(cout)],
                "credits_remaining": self.solde},
                {"X-Spavik-Predictions-Remaining": str(self.solde)})

        if chemin.endswith("/predictions"):
            n = min(int(requete.url.params.get("limit", 50)), self._scores)
            return self._json(200, [{"request_id": f"req_p{i:04d}", "prediction": 1,
                                     "scored_at": "2026-09-14T10:00:00Z"} for i in range(n)])

        if chemin.endswith("/outcomes"):
            recues = len(corps.get("outcomes") or [])
            self.pending_outcomes += recues
            return self._json(201, {"accepted": recues, "pending_outcomes": self.pending_outcomes,
                                    "unresolved": [], "refresh_suggested": recues > 2})

        if chemin.endswith("/refresh"):
            if not self.pending_outcomes:
                return self._json(409, {"status": "error", "message": "NO_PENDING_OUTCOMES",
                                        "messageDetail": "Nothing to integrate."})
            applique, self.pending_outcomes = self.pending_outcomes, 0
            mid = chemin.split("/")[3]
            self.modeles.setdefault(mid, {"id": mid})["latest_version"] = 2
            return self._json(201, {"model": self.modeles[mid],
                                    "version": {"version": 2, "id": "ver_2"},
                                    "outcomes_applied": applique,
                                    "incomplete_outcomes": 0, "context_size": 42})

        if chemin.endswith("/performance"):
            return self._json(200, {"model_id": chemin.split("/")[3], "version": 2,
                                    "task": "classification", "pending_outcomes": 0,
                                    "refresh_suggested": False,
                                    "training_metrics": {"accuracy": 0.9},
                                    "observed": {"accuracy": 1.0, "n": 3}})

        if chemin == "/v1/forecast":
            horizon = corps.get("horizon") or 1
            if horizon > self.solde:
                return self._json(402, {"status": "error", "message": "CREDITS_EXHAUSTED",
                                        "messageDetail": "Not enough credits.",
                                        "balance": self.solde})
            self.solde -= horizon
            cible = corps.get("target") or "valeur"
            lignes = [f"date,{cible}_prediction"]
            lignes += [f"2026-08-{i + 1:02d},{100 + i}" for i in range(horizon)]
            return self._json(200, {
                "target": cible, "prediction_length": horizon,
                "n_context": len(corps.get("data") or []), "n_series": 1,
                "point_estimate": "mean",
                "forecast_csv": "\n".join(lignes) + "\n"},
                {"X-Spavik-Predictions-Remaining": str(self.solde)})

        if chemin.endswith(("/archive", "/restore")) or requete.method == "DELETE":
            mid = chemin.split("/")[3]
            if mid not in self.modeles:
                return self._json(404, {"status": "error", "message": "MODEL_NOT_FOUND",
                                        "messageDetail": "No such model."})
            if requete.method == "DELETE":
                # Suppression definitive : artefacts purges. Hors perimetre client.
                del self.modeles[mid]
                return httpx.Response(204, headers={"x-request-id": "req_simule204"})
            # Archive : sort du quota et du catalogue, artefacts conserves ;
            # restore : reprend sa place.
            self.modeles[mid]["status"] = "archived" if chemin.endswith("/archive") else "ready"
            return self._json(200, {"model": self.modeles[mid]})

        if chemin.startswith("/v1/models/"):
            mid = chemin.split("/")[3]
            if mid in self.modeles and self.modeles[mid].get("status") == "archived":
                # Comme la vraie API : lire ou servir un modele archive est refuse.
                return self._json(409, {"status": "error", "message": "MODEL_ARCHIVED",
                                        "messageDetail": "This model is archived and serves nothing. "
                                                         "Restore it to use it again."})
            if mid in self.modeles:
                return self._json(200, {"model": self.modeles[mid]})
            return self._json(404, {"status": "error", "message": "MODEL_NOT_FOUND",
                                    "messageDetail": "No such model."})

        # Route inconnue : la vraie API rend la page d'erreur du serveur, en HTML.
        return httpx.Response(
            404, text="<!DOCTYPE html>\n<html><body><pre>Cannot POST " + chemin + "</pre></body></html>",
            headers={"content-type": "text/html; charset=utf-8", "x-request-id": "req_html"})

    @staticmethod
    def _json(statut: int, corps: Any, entetes: Optional[Dict[str, str]] = None) -> httpx.Response:
        return httpx.Response(statut, json=corps,
                              headers={"x-request-id": f"req_simule{statut}", **(entetes or {})})
