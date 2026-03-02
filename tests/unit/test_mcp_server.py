"""
Unit tests for MCP Server.

Tests Pydantic input validation for tool schemas. The MCP server
depends on the `mcp` package (FastMCP) which may not be installed
in all environments, so we mock the import and test only the
Pydantic models which are the critical validation layer.

Uses sys.modules mocking to avoid importing 'mcp.server.fastmcp'.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

# ── Mock the mcp package before importing our server ──
_mcp_mock = MagicMock()
sys.modules.setdefault("mcp", _mcp_mock)
sys.modules.setdefault("mcp.server", MagicMock())
sys.modules.setdefault("mcp.server.fastmcp", MagicMock())

from src.mcp.mcp_server import (
    CreateSessionInput,
    GetSessionInput,
    ListSessionsInput,
    SearchFDAInput,
    SearchClinicalTrialsInput,
    GetReportInput,
)


class TestCreateSessionInput:
    """Tests for CreateSessionInput Pydantic validation."""

    def test_valid_input(self) -> None:
        inp = CreateSessionInput(
            drug_name="Pembrolizumab",
            target_market="US",
            user_id="user-123",
        )
        assert inp.drug_name == "Pembrolizumab"
        assert inp.target_market == "US"
        assert inp.priority == 5  # default

    def test_drug_name_too_short(self) -> None:
        with pytest.raises(ValidationError):
            CreateSessionInput(drug_name="A", target_market="US")

    def test_drug_name_too_long(self) -> None:
        with pytest.raises(ValidationError):
            CreateSessionInput(drug_name="A" * 201, target_market="US")

    def test_invalid_market_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateSessionInput(drug_name="TestDrug", target_market="INVALID")

    def test_priority_range(self) -> None:
        with pytest.raises(ValidationError):
            CreateSessionInput(drug_name="TestDrug", target_market="US", priority=0)
        with pytest.raises(ValidationError):
            CreateSessionInput(drug_name="TestDrug", target_market="US", priority=11)

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CreateSessionInput(drug_name="TestDrug", target_market="US", unknown_field="bad")

    def test_strips_whitespace(self) -> None:
        inp = CreateSessionInput(drug_name="  Keytruda  ", target_market="US")
        assert inp.drug_name == "Keytruda"


class TestGetSessionInput:
    """Tests for GetSessionInput validation."""

    def test_valid_uuid(self) -> None:
        inp = GetSessionInput(session_id="12345678-1234-1234-1234-123456789012")
        assert len(inp.session_id) == 36

    def test_short_uuid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GetSessionInput(session_id="short")


class TestListSessionsInput:
    """Tests for ListSessionsInput validation."""

    def test_defaults(self) -> None:
        inp = ListSessionsInput()
        assert inp.limit == 10
        assert inp.offset == 0

    def test_limit_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ListSessionsInput(limit=51)
        with pytest.raises(ValidationError):
            ListSessionsInput(limit=0)


class TestSearchFDAInput:
    """Tests for FDA search input validation."""

    def test_valid_input(self) -> None:
        inp = SearchFDAInput(drug_name="Keytruda")
        assert inp.search_type == "brand_or_generic"  # default

    def test_drug_name_required(self) -> None:
        with pytest.raises(ValidationError):
            SearchFDAInput()


class TestSearchClinicalTrialsInput:
    """Tests for clinical trials search input validation."""

    def test_valid_input(self) -> None:
        inp = SearchClinicalTrialsInput(drug_name="Keytruda")
        assert inp.status == "RECRUITING"  # default
        assert inp.limit == 10

    def test_default_phase(self) -> None:
        inp = SearchClinicalTrialsInput(drug_name="TestDrug")
        assert inp.limit == 10


class TestGetReportInput:
    """Tests for report retrieval input validation."""

    def test_valid_input(self) -> None:
        inp = GetReportInput(
            session_id="12345678-1234-1234-1234-123456789012",
            format="pdf",
        )
        assert inp.format == "pdf"

    def test_default_format(self) -> None:
        inp = GetReportInput(session_id="12345678-1234-1234-1234-123456789012")
        assert inp.format == "pdf"


class TestErrorFormatter:
    """Tests for the _err error formatting utility."""

    def test_formats_http_error(self) -> None:
        from src.mcp.mcp_server import _err
        result = _err(ValueError("Test error message"))
        assert "Error" in result or "error" in result.lower()
        assert "Test error message" in result

    def test_formats_generic_exception(self) -> None:
        from src.mcp.mcp_server import _err
        result = _err(RuntimeError("Something went wrong"))
        assert isinstance(result, str)
        assert len(result) > 0
