from __future__ import annotations

from src.demo.fixture_loader import get_fixture_loader
from src.shared.models.enums import PillarType
from src.shared.models.schemas import QueryParameters, TaskNode
from src.shared.ports.decomposition_engine import DecompositionEngine


class FixtureDecomposer(DecompositionEngine):
    """Offline deterministic decomposer for standalone demo mode."""

    def decompose(self, query: str, session_id: str) -> tuple[QueryParameters, list[TaskNode]]:
        loader = get_fixture_loader()
        bundle = loader.load_decomposition(query)
        qp = QueryParameters.model_validate(bundle.query_parameters)

        tasks: list[TaskNode] = []
        for item in bundle.tasks:
            tasks.append(
                TaskNode(
                    session_id=session_id,
                    pillar=PillarType(item["pillar"]),
                    description=item["description"],
                    parameters=item.get("parameters", {}),
                )
            )
        return qp, tasks

    def close(self) -> None:
        return
