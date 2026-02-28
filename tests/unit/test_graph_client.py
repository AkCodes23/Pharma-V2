"""
Unit tests for Graph Client (Neo4j + Cosmos Gremlin).

Tests entity ingestion, graph queries, and the NER-based
entity extraction with mocked database connections.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.shared.infra.graph_client import GraphClient, _escape


class TestGraphClientNeo4j:
    """Tests for Neo4j backend operations."""

    def setup_method(self) -> None:
        self.client = GraphClient()
        # Mock Neo4j driver
        self.mock_driver = MagicMock()
        self.mock_session = MagicMock()
        self.mock_driver.session.return_value.__enter__ = MagicMock(return_value=self.mock_session)
        self.mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        self.client._driver = self.mock_driver
        self.client._initialized = True
        self.client._use_gremlin = False

    def test_upsert_drug(self) -> None:
        self.client.upsert_drug("Pembrolizumab", {"indication": "Melanoma"})
        self.mock_session.run.assert_called_once()

    def test_upsert_company(self) -> None:
        self.client.upsert_company("Merck")
        self.mock_session.run.assert_called_once()

    def test_upsert_indication(self) -> None:
        self.client.upsert_indication("Melanoma")
        self.mock_session.run.assert_called_once()

    def test_link_drug_treats(self) -> None:
        self.client.link_drug_treats("Pembrolizumab", "Melanoma")
        self.mock_session.run.assert_called_once()

    def test_link_company_owns(self) -> None:
        self.client.link_company_owns("Merck", "Pembrolizumab")
        self.mock_session.run.assert_called_once()

    def test_link_drug_competes(self) -> None:
        self.client.link_drug_competes("Pembrolizumab", "Nivolumab")
        self.mock_session.run.assert_called_once()

    def test_find_drug_competitors(self) -> None:
        mock_result = [{"competitor": "Nivolumab", "owner": "BMS"}]
        self.mock_session.run.return_value = [MagicMock(**{"__iter__": lambda s: iter(mock_result)})]
        # This tests that the method runs without error
        self.client.find_drug_competitors("Pembrolizumab")
        self.mock_session.run.assert_called_once()


class TestGraphClientNoConnection:
    """Tests for graceful degradation when no connection."""

    def setup_method(self) -> None:
        self.client = GraphClient()
        # No driver, no gremlin client
        self.client._initialized = False

    def test_upsert_drug_noop(self) -> None:
        self.client.upsert_drug("Test")  # Should not raise

    def test_find_competitors_returns_empty(self) -> None:
        result = self.client.find_drug_competitors("Test")
        assert result == []

    def test_find_by_indication_returns_empty(self) -> None:
        result = self.client.find_drug_by_indication("Melanoma")
        assert result == []

    def test_multi_hop_returns_empty(self) -> None:
        result = self.client.multi_hop_query("Merck")
        assert result == []


class TestGraphClientGremlin:
    """Tests for Gremlin backend operations."""

    def setup_method(self) -> None:
        self.client = GraphClient()
        self.mock_gremlin = MagicMock()
        self.client._gremlin_client = self.mock_gremlin
        self.client._initialized = True
        self.client._use_gremlin = True

        # Mock successful Gremlin execution
        mock_result_set = MagicMock()
        mock_result_set.all.return_value.result.return_value = []
        self.mock_gremlin.submit.return_value = mock_result_set

    def test_upsert_drug_gremlin(self) -> None:
        self.client.upsert_drug("Pembrolizumab")
        self.mock_gremlin.submit.assert_called_once()
        call_args = self.mock_gremlin.submit.call_args[0][0]
        assert "Pembrolizumab" in call_args
        assert "addV('Drug')" in call_args

    def test_upsert_company_gremlin(self) -> None:
        self.client.upsert_company("Merck")
        self.mock_gremlin.submit.assert_called_once()
        call_args = self.mock_gremlin.submit.call_args[0][0]
        assert "addV('Company')" in call_args

    def test_link_drug_treats_gremlin(self) -> None:
        self.client.link_drug_treats("Pembrolizumab", "Melanoma")
        self.mock_gremlin.submit.assert_called_once()
        call_args = self.mock_gremlin.submit.call_args[0][0]
        assert "TREATS" in call_args


class TestEscapeFunction:
    """Tests for Gremlin string escaping."""

    def test_escapes_single_quotes(self) -> None:
        assert _escape("it's a test") == "it\\'s a test"

    def test_plain_text_unchanged(self) -> None:
        assert _escape("simple") == "simple"

    def test_empty_string(self) -> None:
        assert _escape("") == ""
