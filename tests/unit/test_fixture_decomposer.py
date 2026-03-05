from __future__ import annotations

from src.shared.adapters.fixture_decomposer import FixtureDecomposer
from src.shared.models.enums import PillarType


def test_fixture_decomposer_uses_known_query_fixture() -> None:
    decomposer = FixtureDecomposer()
    params, tasks = decomposer.decompose(
        query="Assess 2027 generic launch for Keytruda in India",
        session_id="session-1",
    )

    assert params.drug_name == "Pembrolizumab"
    assert params.target_market == "India"
    assert len(tasks) == 6
    assert {task.pillar for task in tasks} == {
        PillarType.LEGAL,
        PillarType.CLINICAL,
        PillarType.COMMERCIAL,
        PillarType.SOCIAL,
        PillarType.KNOWLEDGE,
        PillarType.NEWS,
    }


def test_fixture_decomposer_falls_back_to_default_fixture() -> None:
    decomposer = FixtureDecomposer()
    params, tasks = decomposer.decompose(
        query="Analyze unknown molecule strategy",
        session_id="session-2",
    )

    assert params.drug_name == "Unknown"
    assert params.target_market == "Global"
    assert len(tasks) == 6
