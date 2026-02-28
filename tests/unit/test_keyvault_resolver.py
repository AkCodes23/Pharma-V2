"""
Unit tests for Azure Key Vault Secret Resolver.

Tests cover: env var injection, skip-when-already-set behavior,
missing vault URL fallback, and validation helpers.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestResolveSecrets:
    """Tests for resolve_secrets_from_keyvault."""

    def test_skips_when_no_vault_url(self):
        """Returns empty dict when KEY_VAULT_URL is not set."""
        from src.shared.infra.keyvault_resolver import resolve_secrets_from_keyvault

        with patch.dict(os.environ, {}, clear=False):
            # Remove KEY_VAULT_URL if it exists
            os.environ.pop("KEY_VAULT_URL", None)
            result = resolve_secrets_from_keyvault()
            assert result == {}

    def test_skips_when_azure_identity_not_installed(self):
        """Gracefully returns empty when azure-identity is missing."""
        from src.shared.infra.keyvault_resolver import resolve_secrets_from_keyvault

        with patch.dict(os.environ, {"KEY_VAULT_URL": "https://test.vault.azure.net/"}, clear=False):
            with patch("builtins.__import__", side_effect=ImportError("no azure")):
                result = resolve_secrets_from_keyvault()
                assert result == {}

    def test_does_not_override_existing_env_vars(self):
        """Existing env vars should NOT be overwritten by default."""
        from src.shared.infra.keyvault_resolver import resolve_secrets_from_keyvault

        with patch.dict(os.environ, {
            "KEY_VAULT_URL": "https://test.vault.azure.net/",
            "AZURE_OPENAI_API_KEY": "already-set",
        }, clear=False):
            mock_client = MagicMock()
            mock_secret = MagicMock()
            mock_secret.value = "from-vault"

            mock_client.get_secret.return_value = mock_secret

            with patch("src.shared.infra.keyvault_resolver.DefaultAzureCredential", return_value=MagicMock()):
                with patch("src.shared.infra.keyvault_resolver.SecretClient", return_value=mock_client):
                    resolve_secrets_from_keyvault(override_existing=False)
                    # Should NOT have been overwritten
                    assert os.environ["AZURE_OPENAI_API_KEY"] == "already-set"


class TestSecretMap:
    """Tests for the secret mapping configuration."""

    def test_secret_map_has_required_entries(self):
        """All critical Azure services must be in the secret map."""
        from src.shared.infra.keyvault_resolver import _SECRET_MAP

        required_mappings = [
            "azure-openai-api-key",
            "cosmos-db-key",
            "service-bus-connection-string",
            "ai-search-api-key",
            "redis-url",
        ]
        for secret_name in required_mappings:
            assert secret_name in _SECRET_MAP, f"Missing required secret: {secret_name}"

    def test_secret_map_env_vars_are_valid(self):
        """All mapped env var names should be uppercase with underscores."""
        from src.shared.infra.keyvault_resolver import _SECRET_MAP

        for secret_name, env_var in _SECRET_MAP.items():
            assert env_var == env_var.upper(), f"Env var should be uppercase: {env_var}"
            assert " " not in env_var, f"Env var should not have spaces: {env_var}"


class TestGetMissingSecrets:
    """Tests for get_missing_secrets validation helper."""

    def test_reports_missing_required_secrets(self):
        """Should return list of missing env vars."""
        from src.shared.infra.keyvault_resolver import get_missing_secrets

        with patch.dict(os.environ, {}, clear=True):
            missing = get_missing_secrets()
            assert "AZURE_OPENAI_API_KEY" in missing
            assert "COSMOS_DB_KEY" in missing

    def test_reports_empty_when_all_present(self):
        """Should return empty list when all required secrets are set."""
        from src.shared.infra.keyvault_resolver import get_missing_secrets

        with patch.dict(os.environ, {
            "AZURE_OPENAI_API_KEY": "test",
            "AZURE_OPENAI_ENDPOINT": "test",
            "COSMOS_DB_KEY": "test",
            "COSMOS_DB_ENDPOINT": "test",
            "SERVICE_BUS_CONNECTION_STRING": "test",
        }, clear=False):
            missing = get_missing_secrets()
            assert missing == []
