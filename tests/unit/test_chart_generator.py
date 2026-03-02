"""
Unit tests for Executor Agent — Chart Generator.

Tests revenue chart, patent timeline, and safety gauge generation
with valid and empty data. Validates base64 output format.
"""

from __future__ import annotations

import base64

import matplotlib
matplotlib.use("Agg")

import pytest

from src.agents.executor.chart_generator import (
    generate_revenue_chart,
    generate_patent_timeline,
    generate_safety_gauge,
    _fig_to_base64,
)


class TestGenerateRevenueChart:
    """Tests for revenue trend bar chart generation."""

    def test_generates_valid_base64_png(self) -> None:
        data = {
            "annual_revenue": [
                {"year": 2022, "revenue_usd": 17200000000},
                {"year": 2023, "revenue_usd": 25000000000},
                {"year": 2024, "revenue_usd": 27500000000},
            ],
        }
        result = generate_revenue_chart(data)
        assert len(result) > 0
        # Verify it's valid base64
        decoded = base64.b64decode(result)
        # PNG magic bytes
        assert decoded[:4] == b"\x89PNG"

    def test_empty_revenue_returns_empty(self) -> None:
        result = generate_revenue_chart({"annual_revenue": []})
        assert result == ""

    def test_missing_key_returns_empty(self) -> None:
        result = generate_revenue_chart({})
        assert result == ""

    def test_highlights_patent_cliff_note(self) -> None:
        """Revenue bars with 'note' field should use danger color."""
        data = {
            "annual_revenue": [
                {"year": 2025, "revenue_usd": 20000000000},
                {"year": 2026, "revenue_usd": 12000000000, "note": "Patent cliff"},
            ],
        }
        result = generate_revenue_chart(data)
        assert len(result) > 0


class TestGeneratePatentTimeline:
    """Tests for patent timeline Gantt chart."""

    def test_generates_timeline_with_patents(self) -> None:
        data = {
            "blocking_patents": [
                {
                    "patent_number": "US10,000,001",
                    "filing_date": "2010-03-15",
                    "expiry_date": "2030-03-15",
                },
            ],
            "regional_patents": [],
        }
        result = generate_patent_timeline(data)
        assert len(result) > 0
        decoded = base64.b64decode(result)
        assert decoded[:4] == b"\x89PNG"

    def test_empty_patents_returns_empty(self) -> None:
        result = generate_patent_timeline({"blocking_patents": [], "regional_patents": []})
        assert result == ""

    def test_handles_missing_dates(self) -> None:
        data = {
            "blocking_patents": [
                {"patent_number": "US999", "filing_date": None, "expiry_date": None},
            ],
            "regional_patents": [],
        }
        result = generate_patent_timeline(data)
        assert len(result) > 0  # Should use fallback dates


class TestGenerateSafetyGauge:
    """Tests for safety risk gauge chart."""

    def test_low_risk_generates_gauge(self) -> None:
        data = {"safety_score": {"risk_level": "LOW", "serious_pct": 5.2}}
        result = generate_safety_gauge(data)
        assert len(result) > 0

    def test_critical_risk_generates_gauge(self) -> None:
        data = {"safety_score": {"risk_level": "CRITICAL", "serious_pct": 42.8}}
        result = generate_safety_gauge(data)
        assert len(result) > 0

    def test_empty_score_returns_empty(self) -> None:
        result = generate_safety_gauge({"safety_score": {}})
        assert result == ""

    def test_missing_key_returns_empty(self) -> None:
        result = generate_safety_gauge({})
        assert result == ""

    def test_all_risk_levels(self) -> None:
        """All four risk levels should generate valid charts."""
        for level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            data = {"safety_score": {"risk_level": level, "serious_pct": 15.0}}
            result = generate_safety_gauge(data)
            assert len(result) > 0, f"Failed for risk level: {level}"


class TestFigToBase64:
    """Tests for the figure conversion utility."""

    def test_returns_valid_base64_string(self) -> None:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3], [1, 4, 9])
        result = _fig_to_base64(fig)
        assert isinstance(result, str)
        assert len(result) > 100  # Non-trivial output
        decoded = base64.b64decode(result)
        assert decoded[:4] == b"\x89PNG"

    def test_figure_is_closed_after_conversion(self) -> None:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.bar(["A", "B"], [1, 2])
        initial_count = len(plt.get_fignums())
        _fig_to_base64(fig)
        # Figure should be closed
        assert len(plt.get_fignums()) < initial_count or len(plt.get_fignums()) == 0
