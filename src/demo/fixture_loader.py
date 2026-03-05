from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.shared.models.enums import PillarType
from src.shared.models.schemas import TaskNode


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _slug(value: str) -> str:
    return _normalize(value).replace(" ", "_")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FixtureBundle:
    query_parameters: dict[str, Any]
    tasks: list[dict[str, Any]]


class FixtureLoader:
    """Loads deterministic standalone-demo fixtures from src/demo/fixtures."""

    def __init__(self) -> None:
        self._root = Path(__file__).resolve().parent / "fixtures"

    def _read_json(self, relative_path: str) -> dict[str, Any]:
        path = self._root / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def load_decomposition(self, query: str) -> FixtureBundle:
        normalized = _normalize(query)
        if "keytruda" in normalized or "pembrolizumab" in normalized:
            payload = self._read_json("decomposition/keytruda_india_2027.json")
        elif "semaglutide" in normalized or "ozempic" in normalized:
            payload = self._read_json("decomposition/semaglutide_us_2027.json")
        else:
            payload = self._read_json("decomposition/default.json")

        return FixtureBundle(
            query_parameters=payload["query_parameters"],
            tasks=payload["tasks"],
        )

    def load_retriever_output(
        self,
        pillar: PillarType,
        task: TaskNode,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        params = task.parameters or {}
        drug_name = str(params.get("drug_name") or params.get("ingredient") or "unknown")
        market = str(params.get("target_market") or "global")
        drug_slug = _slug(drug_name)

        candidate = self._root / pillar.value.lower() / f"{drug_slug}.json"
        default_path = self._root / pillar.value.lower() / "default.json"
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        elif default_path.exists():
            payload = json.loads(default_path.read_text(encoding="utf-8"))
        else:
            payload = self._build_fallback_payload(pillar, drug_name, market, task.description)

        findings = dict(payload.get("findings", {}))
        citations = list(payload.get("citations", []))
        if not citations:
            citations = [
                {
                    "source_name": f"Standalone Fixture - {pillar.value}",
                    "source_url": "local://fixtures",
                    "retrieved_at": "2026-01-01T00:00:00+00:00",
                    "data_hash": _hash(f"{pillar.value}:{drug_name}:{market}:{task.description}"),
                    "excerpt": "Deterministic demo fixture response",
                }
            ]
        return findings, citations

    def render_report_template(self) -> str:
        return (self._root / "reports" / "templates" / "default.md").read_text(encoding="utf-8")

    def _build_fallback_payload(
        self,
        pillar: PillarType,
        drug_name: str,
        market: str,
        description: str,
    ) -> dict[str, Any]:
        base_hash = _hash(f"{pillar.value}:{drug_name}:{market}:{description}")
        return {
            "findings": {
                "drug_name": drug_name,
                "target_market": market,
                "note": "Fallback deterministic mock response",
                "summary": f"{pillar.value} offline fixture generated for {drug_name}",
            },
            "citations": [
                {
                    "source_name": f"Standalone Fallback - {pillar.value}",
                    "source_url": "local://fixtures/fallback",
                    "retrieved_at": "2026-01-01T00:00:00+00:00",
                    "data_hash": base_hash,
                    "excerpt": "Generated fallback mock payload",
                }
            ],
        }


_loader: FixtureLoader | None = None


def get_fixture_loader() -> FixtureLoader:
    global _loader
    if _loader is None:
        _loader = FixtureLoader()
    return _loader
